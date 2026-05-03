"""
Learn Quran — AI Study Assistant
Single entrypoint for Hugging Face Spaces (Gradio SDK).
FastAPI routes /ready and /chat are mounted alongside a Gradio UI at /.
"""

import os
import json
import logging
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import quote as url_quote

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import gradio as gr

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Paths & edition config ─────────────────────────────────────────────────

CACHE_DIR = Path("./data/quran_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_JSDELIVR_BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@1/editions"
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/fawazahmed0/quran-api/1/editions"

EDITIONS = {
    "arabic": {
        "name": "ar.quran-uthmani",
        "url": f"{_JSDELIVR_BASE}/ar.quran-uthmani.json",
        "fallback_url": f"{_GITHUB_RAW_BASE}/ar.quran-uthmani.json",
        "cache": CACHE_DIR / "ar.quran-uthmani.json",
    },
    "urdu": {
        "name": "ur.jalandhry",
        "url": f"{_JSDELIVR_BASE}/ur.jalandhry.json",
        "fallback_url": f"{_GITHUB_RAW_BASE}/ur.jalandhry.json",
        "cache": CACHE_DIR / "ur.jalandhry.json",
    },
}

ALQURAN_SEARCH_URL = "https://api.alquran.cloud/v1/search/{word}/all/ar"

# ─── Lazy-load state ────────────────────────────────────────────────────────

_arabic_lookup: dict[tuple[int, int], str] = {}   # (surah, ayah) -> arabic text
_urdu_lookup: dict[tuple[int, int], str] = {}     # (surah, ayah) -> urdu text
_editions_loaded: bool = False
_editions_error: Optional[str] = None
_editions_lock = threading.Lock()  # prevents duplicate downloads on concurrent requests


def _download_edition(name: str, url: str, cache_path: Path, fallback_url: Optional[str] = None) -> dict:
    """Return edition JSON from disk cache, or download and cache it.

    If the primary *url* raises a :class:`requests.RequestException` (e.g. 403/404),
    and *fallback_url* is provided, that URL is tried before propagating the error.
    """
    if cache_path.exists():
        logger.info("Loading %s from cache: %s", name, cache_path)
        with open(cache_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    candidate_urls = [url]
    if fallback_url:
        candidate_urls.append(fallback_url)

    last_exc: Optional[Exception] = None
    for attempt_url in candidate_urls:
        logger.info("Downloading %s from %s", name, attempt_url)
        try:
            resp = requests.get(attempt_url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            return data
        except requests.RequestException as exc:
            logger.error("Failed to download %s from %s: %s", name, attempt_url, exc)
            last_exc = exc
            if attempt_url == fallback_url or fallback_url is None:
                break
            logger.info("Trying fallback URL for %s", name)

    raise last_exc  # always set: loop only exits via break after an exception


def _build_lookup(data: dict) -> dict:
    """
    Build (surah, ayah) -> text lookup from fawazahmed0/quran-api JSON.
    Expected format: {"quran": [{"chapter": int, "verse": int, "text": str}, ...]}
    """
    lookup: dict = {}
    verses = data.get("quran", [])
    for verse in verses:
        key = (int(verse["chapter"]), int(verse["verse"]))
        lookup[key] = verse.get("text", "")
    return lookup


def ensure_editions_loaded() -> bool:
    """Attempt to load editions into memory. Returns True on success."""
    global _arabic_lookup, _urdu_lookup, _editions_loaded, _editions_error

    if _editions_loaded:
        return True

    with _editions_lock:
        # Re-check inside the lock in case another thread loaded while we waited.
        if _editions_loaded:
            return True

        try:
            arabic_data = _download_edition(
                "Arabic Uthmani",
                EDITIONS["arabic"]["url"],
                EDITIONS["arabic"]["cache"],
                EDITIONS["arabic"].get("fallback_url"),
            )
            _arabic_lookup = _build_lookup(arabic_data)

            urdu_data = _download_edition(
                "Urdu Jalandhari",
                EDITIONS["urdu"]["url"],
                EDITIONS["urdu"]["cache"],
                EDITIONS["urdu"].get("fallback_url"),
            )
            _urdu_lookup = _build_lookup(urdu_data)

            _editions_loaded = True
            _editions_error = None
            logger.info("Editions loaded: %d verses", len(_arabic_lookup))
            return True

        except (requests.RequestException, json.JSONDecodeError, OSError) as exc:
            _editions_error = str(exc)
            logger.error("Failed to load editions: %s", exc)
            return False


# Attempt a non-fatal background preload so the first /chat is faster.
try:
    ensure_editions_loaded()
except Exception:  # noqa: BLE001
    pass

# ─── FastAPI ─────────────────────────────────────────────────────────────────

_fastapi_app = FastAPI(title="Learn Quran API")


class ChatRequest(BaseModel):
    message: str
    ayah_ref: Optional[str] = None
    target_word: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    citations: list[str]


def _parse_ayah_ref(ref: str) -> Optional[tuple[int, int]]:
    """Parse 'surah:ayah' string into (surah, ayah) int tuple, or return None."""
    try:
        parts = ref.strip().split(":")
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
    except ValueError:
        pass
    return None


def _search_word_alquran(word: str) -> list[str]:
    """
    Search AlQuran.cloud for verses containing *word*.
    Returns up to 5 'surah:ayah' reference strings.
    Falls back to [] on any network/API error.
    """
    try:
        url = ALQURAN_SEARCH_URL.format(word=url_quote(word))
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        matches = data.get("data", {}).get("matches", [])
        refs: list[str] = []
        for m in matches[:5]:
            surah = m.get("surah", {}).get("number")
            ayah = m.get("numberInSurah")
            if surah and ayah:
                refs.append(f"{surah}:{ayah}")
        return refs
    except requests.RequestException as exc:
        logger.warning("AlQuran.cloud search failed for '%s': %s", word, exc)
        return []


def _build_context(
    ayah_ref: Optional[str], target_word: Optional[str]
) -> tuple[str, list[str]]:
    """
    Return (context_string, citations_list) for the given inputs.
    Calls ensure_editions_loaded() to trigger lazy loading.
    """
    ensure_editions_loaded()

    citations: list[str] = []
    context_parts: list[str] = []

    def _add_verse(ref_str: str) -> None:
        parsed = _parse_ayah_ref(ref_str)
        if not parsed:
            return
        surah, ayah = parsed
        arabic = _arabic_lookup.get((surah, ayah), "")
        urdu = _urdu_lookup.get((surah, ayah), "")
        if arabic or urdu:
            citations.append(ref_str)
            context_parts.append(
                f"[{ref_str}]\nArabic: {arabic}\nUrdu: {urdu}"
            )

    if ayah_ref:
        _add_verse(ayah_ref.strip())

    if target_word:
        refs = _search_word_alquran(target_word)
        for ref in refs:
            if ref not in citations:
                _add_verse(ref)

    context = "\n\n".join(context_parts) if context_parts else "No specific verses provided."
    return context, citations


SYSTEM_PROMPT = (
    "You are a Quran study assistant. Your role is to help users understand "
    "and study the Quran.\n\n"
    "Rules:\n"
    "- Only answer questions related to Quran study, tafsir, Arabic vocabulary, "
    "and Islamic education.\n"
    "- Do not issue fatwas or religious rulings.\n"
    "- Do not add verse text that is not present in the provided Context.\n"
    "- Keep responses concise and educational.\n"
    "- Format your response with short explanatory points followed by "
    "'References: [list of surah:ayah]'.\n"
    "- If the question is outside your scope, politely explain your limitations."
)


@_fastapi_app.get("/ready")
def ready() -> dict:
    """Health / readiness check."""
    groq_key = os.getenv("GROQ_API_KEY")
    # Avoid exposing raw exception messages from internal systems.
    has_editions_error = _editions_error is not None
    return {
        "status": "ok",
        "groq_key_configured": bool(groq_key),
        "editions_loaded": _editions_loaded,
        "editions_error": has_editions_error,
        "verse_count": len(_arabic_lookup),
    }


@_fastapi_app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Main chat endpoint."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GROQ_API_KEY is not configured. "
                "Please add it in Space Settings → Variables and secrets."
            ),
        )

    from groq import Groq  # imported lazily to keep startup fast

    client = Groq(api_key=groq_key)
    context, citations = _build_context(req.ayah_ref, req.target_word)

    user_message = f"Context:\n{context}\n\nQuestion: {req.message}"

    try:
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=512,
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 — groq SDK may raise various errors
        logger.error("Groq API error: %s", exc)
        # Provide a more specific message for common failure modes.
        detail = "Failed to get a response from the language model. Please try again."
        status = 502
        exc_name = type(exc).__name__
        if "Authentication" in exc_name or "auth" in exc_name.lower():
            detail = "Invalid GROQ_API_KEY. Please check your Space secret."
            status = 401
        elif "RateLimit" in exc_name:
            detail = "Rate limit reached. Please wait a moment and try again."
            status = 429
        raise HTTPException(status_code=status, detail=detail) from exc

    if not completion.choices or completion.choices[0].message.content is None:
        raise HTTPException(
            status_code=502,
            detail="The language model returned an empty response. Please try again.",
        )
    response_text = completion.choices[0].message.content
    return ChatResponse(response=response_text, citations=citations)


# ─── Gradio UI ───────────────────────────────────────────────────────────────

def _status_text() -> str:
    groq_key = os.getenv("GROQ_API_KEY")
    if _editions_loaded:
        data_status = f"✅ loaded ({len(_arabic_lookup)} verses)"
    elif _editions_error:
        data_status = f"❌ {_editions_error}"
    else:
        data_status = "⏳ not yet loaded"
    lines = [
        f"🔑 GROQ key: {'✅ configured' if groq_key else '❌ missing — add in Space Secrets'}",
        f"📖 Quran data: {data_status}",
    ]
    return "\n".join(lines)


def _chat_ui(message: str, ayah_ref: str, target_word: str):
    if not message.strip():
        return (
            "Please enter a question.",
            "",
            _status_text(),
        )

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return (
            "❌ GROQ_API_KEY is not configured. "
            "Add it in Space Settings → Variables and secrets.",
            "",
            _status_text(),
        )

    try:
        ayah_stripped = ayah_ref.strip() if ayah_ref else ""
        word_stripped = target_word.strip() if target_word else ""
        req = ChatRequest(
            message=message,
            ayah_ref=ayah_stripped if ayah_stripped else None,
            target_word=word_stripped if word_stripped else None,
        )
        result = chat(req)
        citations_text = "\n".join(result.citations) if result.citations else "—"
        return result.response, citations_text, _status_text()
    except HTTPException as exc:
        return f"❌ {exc.detail}", "", _status_text()
    except Exception as exc:  # noqa: BLE001
        logger.error("Chat UI error: %s", exc)
        return "❌ An error occurred. Please try again.", "", _status_text()


with gr.Blocks(title="Learn Quran — AI Study Assistant") as demo:
    gr.Markdown("# 📖 Learn Quran — AI Study Assistant")
    gr.Markdown(
        "Ask questions about the Quran. "
        "Optionally provide an Ayah reference (e.g. `2:255`) "
        "or an Arabic word to search (e.g. `تقوى`)."
    )

    with gr.Row():
        with gr.Column(scale=2):
            msg_input = gr.Textbox(
                label="Your Question",
                placeholder="e.g. Explain the concept of taqwa",
                lines=3,
            )
            with gr.Row():
                ayah_input = gr.Textbox(
                    label="Ayah Reference (optional)",
                    placeholder="e.g. 2:255",
                )
                word_input = gr.Textbox(
                    label="Arabic Word to Search (optional)",
                    placeholder="e.g. تقوى",
                )
            submit_btn = gr.Button("Ask", variant="primary")

        with gr.Column(scale=3):
            response_output = gr.Textbox(
                label="Response", lines=10, interactive=False
            )
            citations_output = gr.Textbox(
                label="Citations", lines=3, interactive=False
            )

    status_output = gr.Textbox(
        label="Status", interactive=False, value=_status_text()
    )

    gr.Examples(
        examples=[
            ["What is the meaning of Ayat al-Kursi?", "2:255", ""],
            ["Explain the concept of taqwa", "", "تقوى"],
            ["What does this verse say about patience?", "2:153", ""],
            ["Explain Surah Al-Fatiha", "1:1", ""],
        ],
        inputs=[msg_input, ayah_input, word_input],
    )

    submit_btn.click(
        fn=_chat_ui,
        inputs=[msg_input, ayah_input, word_input],
        outputs=[response_output, citations_output, status_output],
    )
    msg_input.submit(
        fn=_chat_ui,
        inputs=[msg_input, ayah_input, word_input],
        outputs=[response_output, citations_output, status_output],
    )

# Mount Gradio at root "/" so HF Spaces shows the UI on the Space URL.
app = gr.mount_gradio_app(_fastapi_app, demo, path="/")
