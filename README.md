# CareerPath

Career advisor chatbot for University of Northampton students. It covers careers, CVs, placements, and a short interview practice, and it can save anonymous feedback.

The page is a static frontend. Answers come from a local FastAPI backend that calls the OpenAI API.

## Connect an API key after you download this

This download does not include an API key. Chat, CV review, and interview scoring will not work until you connect your own OpenAI account.

1. Create an API key at [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys).
2. In the same terminal you use to start the backend, set it:

```bash
export OPENAI_API_KEY='your-key-here'
```

Do not commit the key or paste it into the frontend. The backend reads `OPENAI_API_KEY` from the environment. If it is missing, the server stops on startup with `OPENAI_API_KEY is not set`.

If the key is missing, invalid, or the API cannot be reached, the chat shows **Something went wrong. Please try again.** Interview practice can still start, because the first question is fixed. Scoring an answer uses the API as well.

## Requirements

- Python 3.10 or newer
- An OpenAI API key with access to the chat and embeddings models

The default models are `gpt-4o-mini` and `text-embedding-3-small`.

## Setup

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY='your-key-here'
```

On Windows PowerShell, set the key with:

```powershell
$env:OPENAI_API_KEY = "your-key-here"
```

## Run

Start the backend first, and leave it running:

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/` should return `{"status":"ok"}`.

In a second terminal, serve the frontend:

```bash
python -m http.server 5500 --directory frontend --bind 127.0.0.1
```

Open [http://127.0.0.1:5500](http://127.0.0.1:5500). Tick the consent box, then start the chat.

The page calls `http://127.0.0.1:8000`. Keep the backend on that address and port.

## What each part calls

| Action | Needs the OpenAI API |
| --- | --- |
| Career chat | Yes |
| CV upload (`.txt`, `.md`, or `.csv`) | Yes |
| Start interview practice | No |
| Score an interview answer | Yes |
| Save feedback ratings | No |

PDF and Word CVs are not parsed. Save the CV as a `.txt` file before uploading it.

## Optional settings

Set these in the environment before starting the backend if you need to change them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Required. Your OpenAI key. |
| `career_chat_model` | `gpt-4o-mini` | Chat and interview model. |
| `career_embedding_model` | `text-embedding-3-small` | Embeddings for the careers documents. |
| `career_estimated_cost_per_1m_tokens_gbp` | `0.47` | Cost estimate written to the logs. |
| `career_log_salt` | `careerpath-local-evaluation` | Salt used to anonymise thread ids. |

## Project layout

- `frontend/` is the home page and chat UI.
- `app.py` is the FastAPI server.
- `career_backend.py` is the career graph, interview practice, and logs.
- `samples.pdf` is the careers material used for retrieval.
- `chroma_db/` is the local vector database built from that PDF. Keep it beside `career_backend.py`. If it is missing, the backend rebuilds it on startup, which also calls the embeddings API.
- `anonymous_interaction_log.csv`, `anonymous_interview_practice_log.csv`, and `anonymous_feedback_log.csv` store evaluation data. They do not store the raw thread id.

## Terminal demo

With the key exported and the virtual environment active:

```bash
python career_backend.py
```

Type a question, `summary` to write `evaluation_summary.json`, or `quit` to stop.
