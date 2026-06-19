# Local TTS Gateway

A local Python/FastAPI text-to-speech microservice powered by [Kokoro](https://github.com/hexgrad/kokoro).

Send text to a local API and receive generated speech as a `.wav` file. Useful for macOS selected text, local agents, voiceovers, and experiments.

## Architecture

```txt
Mac selected text / website / agents / scripts
        ↓
POST http://127.0.0.1:8888/tts/wav
        ↓
Python FastAPI service
        ↓
Kokoro engine loaded once (lazy, per language)
        ↓
WAV file returned
```

Kokoro pipelines are loaded once and reused between requests — not reloaded on every call.

## Requirements

- Python 3.10 or 3.11 (3.12+ may work; use the same interpreter for `venv` and running the server)
- macOS (for `afplay` in the selection script)

### System dependency

```bash
brew install espeak-ng
```

## Quick start

Use this every time you open a new terminal and want to run the server.

```bash
cd local-tts-gateway
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8888 --reload
```

Your shell prompt should show `(.venv)` after activation. If `uvicorn` is not found, you skipped `source` — the server must run with the virtualenv's Python, not the system one.

- API: http://127.0.0.1:8888
- Docs: http://127.0.0.1:8888/docs

## First-time setup

Run once after cloning or downloading the project.

```bash
cd local-tts-gateway
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then start the server with the [Quick start](#quick-start) commands above.

### Activate the virtualenv

| Shell | Command |
|-------|---------|
| bash / zsh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

To leave the virtualenv later: `deactivate`

## Health check

```bash
curl http://127.0.0.1:8888/health
```

## Generate a WAV file

```bash
curl -X POST http://127.0.0.1:8888/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello Abed. Kokoro is now running locally as a TTS gateway.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output speech.wav

afplay speech.wav
```

## Save a WAV file and return its path

```bash
curl -X POST http://127.0.0.1:8888/tts/file \
  -H "Content-Type: application/json" \
  -d '{"text":"This file will be saved inside the outputs folder.","voice":"af_heart","speed":1,"lang_code":"a"}'
```

## macOS selected text script

With the server running:

```bash
./scripts/read-selection.sh "Hello. This text was sent from a local script and read using Kokoro."
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |
| GET | `/voices` | Example voices and defaults |
| POST | `/tts/wav` | Generate speech, return `audio/wav` |
| POST | `/tts/file` | Generate speech, save to `outputs/`, return path |

### Request body

```json
{
  "text": "Text to read aloud.",
  "voice": "af_heart",
  "speed": 1,
  "lang_code": "a"
}
```

## Language codes

| Code | Language |
|------|----------|
| `a` | American English |
| `b` | British English |
| `e` | Spanish |
| `f` | French |
| `h` | Hindi |
| `i` | Italian |
| `j` | Japanese |
| `p` | Brazilian Portuguese |
| `z` | Mandarin Chinese |

## Voice examples

- `af_heart`, `af_bella`, `af_sarah`
- `am_adam`, `am_michael`

Voice availability depends on the Kokoro version installed.

## Project structure

```txt
local-tts-gateway/
├─ app/
│  ├─ main.py           # FastAPI routes
│  ├─ config.py         # Settings
│  ├─ schemas.py        # Request/response models
│  ├─ engines/          # TTS engine implementations
│  ├─ services/         # Business logic
│  └─ utils/            # Audio helpers
├─ outputs/             # Generated WAV files
├─ scripts/             # macOS helpers
└─ requirements.txt
```

## Future improvements

- `POST /tts/stream` — streaming audio
- `POST /tts/play` — generate and play via `afplay`
- API key protection
- Request queue for long text
- Browser extension / Raycast command

## Configuration

Copy `.env.example` to `.env`:

```env
APP_HOST=127.0.0.1
APP_PORT=8888
DEFAULT_LANG_CODE=a
DEFAULT_VOICE=af_heart
DEFAULT_SPEED=1.0
OUTPUT_DIR=outputs
```
