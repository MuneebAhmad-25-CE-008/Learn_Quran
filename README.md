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

1. Push this repository to a Hugging Face Space (Gradio SDK).
2. In **Space Settings → Variables and secrets**, add:
   - **Name:** `GROQ_API_KEY`  **Value:** your Groq API key (as a *Secret*)
3. The Space will start automatically. Visit the Space URL to use the UI.

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