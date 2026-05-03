---
title: Learn Quran
emoji: 📖
colorFrom: green
colorTo: teal
sdk: gradio
sdk_version: "6.7.0"
app_file: app.py
pinned: false
---

# 📖 Learn Quran — AI Study Assistant

A Quran study assistant powered by [Groq](https://groq.com/) (LLaMA 3) with Arabic Uthmani and Urdu Jalandhari text lookup from [fawazahmed0/quran-api](https://github.com/fawazahmed0/quran-api).

## Features

- Ask questions about the Quran (tafsir, vocabulary, context)
- Look up any verse by reference (e.g. `2:255`)
- Search for verses containing an Arabic word (e.g. `تقوى`)
- Clean Gradio UI with a FastAPI backend (`/ready`, `/chat`)

## Running Locally

```bash
# 1. Clone and install dependencies
pip install -r requirements.txt

# 2. Create a .env file with your Groq API key
echo "GROQ_API_KEY=your_key_here" > .env

# 3. Start the app
uvicorn app:app --host 0.0.0.0 --port 7860
```

Then open http://localhost:7860 in your browser.

## Deploying to Hugging Face Spaces

### Files required on the Space

Only three files are needed. Do **not** upload `data/`, `.env`, or any other local files.

| File | Purpose |
|------|---------|
| `app.py` | Main application — Gradio UI + FastAPI backend |
| `requirements.txt` | Python dependencies installed by HF on every build |
| `README.md` | Space metadata (the `---` YAML front matter at the top) + documentation |

The `data/quran_cache/` directory is created automatically at runtime and used for caching downloaded Quran JSON files. It is ephemeral (reset on Space restart) and must **not** be committed.

---

### Step-by-step: create the Space and deploy

#### 1. Create a new Space on Hugging Face

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space).
2. Fill in:
   - **Owner** — your HF username or organisation.
   - **Space name** — e.g. `learn-quran`.
   - **License** — choose any (e.g. MIT).
   - **SDK** — select **Gradio**.
   - **SDK version** — `6.7.0` (must match `requirements.txt`).
   - **Visibility** — Public or Private.
3. Click **Create Space**. HF creates a git repository for the Space.

#### 2. Push the files

Option A — via the HF web UI (no git needed):

1. Open your new Space → click **Files** tab → **Add file → Upload files**.
2. Upload `app.py`, `requirements.txt`, and `README.md`.
3. Click **Commit changes to main**.

Option B — via git:

```bash
# Add the HF Space as a remote (replace <owner> and <space-name>)
git remote add space https://huggingface.co/spaces/<owner>/<space-name>

# Push only the three required files
git push space main
```

> **Tip:** If your local repo contains large cached files or a `data/` folder,
> add them to `.gitignore` before pushing so they are not uploaded to the Space.

#### 3. Add the GROQ API key as a Secret

Secrets are environment variables that are kept encrypted and are never shown in logs.

1. In your Space page click **Settings** (gear icon) → scroll to **Variables and secrets**.
2. Click **New secret** and add:
   - **Name:** `GROQ_API_KEY`
   - **Value:** your Groq API key (get one free at [console.groq.com](https://console.groq.com))
3. Click **Save**. The Space restarts automatically and picks up the key.

> Do **not** put the API key in `app.py` or `requirements.txt`. Always use Secrets.

#### 4. Verify the Space is running

1. The **App** tab shows a build log. Wait for `Running` status (usually < 2 minutes).
2. Visit the Space URL — you should see the Gradio UI.
3. Check readiness by opening `<your-space-url>/ready` in a browser. A healthy response looks like:

```json
{
  "status": "ok",
  "groq_key_configured": true,
  "editions_loaded": true,
  "editions_error": false,
  "verse_count": 6236
}
```

If `editions_loaded` is `false`, wait ~30 seconds and refresh — the first cold start downloads the Quran JSON files (~2 MB each). If it stays `false`, check the build log for network errors; the app will automatically retry the fallback mirror on the next restart.

---

### README.md front matter (Space metadata)

The block at the very top of `README.md` is read by Hugging Face to configure the Space:

```yaml
---
title: Learn Quran
emoji: 📖
colorFrom: green
colorTo: teal
sdk: gradio
sdk_version: "6.7.0"
app_file: app.py
pinned: false
---
```

| Field | What it does |
|-------|-------------|
| `sdk` | Must be `gradio` — tells HF which runtime to use |
| `sdk_version` | Must match the `gradio` version in `requirements.txt` |
| `app_file` | The Python file HF launches (`app.py`) |
| `title` / `emoji` / `colorFrom` / `colorTo` | Display name and card styling on the HF hub |
| `pinned` | Set to `true` to pin the Space to the top of your profile |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/ready` | Readiness check — reports GROQ key status and loaded verse count |
| `POST` | `/chat`  | Chat endpoint — `{"message": "...", "ayah_ref": "2:255", "target_word": "تقوى"}` |

### Example `/chat` request

```bash
curl -X POST http://localhost:7860/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain Ayat al-Kursi", "ayah_ref": "2:255"}'
```

Response:

```json
{
  "response": "Ayat al-Kursi (2:255) is known as the Throne Verse ...",
  "citations": ["2:255"]
}
```