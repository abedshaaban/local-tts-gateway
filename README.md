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

Then bootstrap the Kokoro model (requires internet once):

```bash
python scripts/bootstrap_kokoro.py
```

Then start the server with the [Quick start](#quick-start) commands above.

### Activate the virtualenv

| Shell | Command |
|-------|---------|
| bash / zsh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

To leave the virtualenv later: `deactivate`

## Running Fully Local / Offline

This project can run without contacting Hugging Face after Kokoro has been downloaded once.

### 1. Bootstrap Kokoro once

Run this while connected to the internet:

```bash
source .venv/bin/activate
python scripts/bootstrap_kokoro.py
```

This downloads and caches the Kokoro model locally.

### 2. Enable offline mode

Create `.env`:

```bash
cp .env.example .env
```

Make sure these values exist:

```env
KOKORO_LOCAL_ONLY=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HOME=.cache/huggingface
KOKORO_REPO_ID=hexgrad/Kokoro-82M
```

### 3. Start the server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8888 --reload
```

### 4. Test offline WAV generation

```bash
curl -X POST http://127.0.0.1:8888/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"This is running locally without calling Hugging Face.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output offline-test.wav

afplay offline-test.wav
```

### 5. Test offline PCM streaming

```bash
curl -N -X POST http://127.0.0.1:8888/tts/stream/pcm \
  -H "Content-Type: application/json" \
  -d '{"text":"Offline chunk one.\nOffline chunk two.\nOffline chunk three.","voice":"af_heart","speed":1,"lang_code":"a","split_pattern":"\\n+"}' \
  --output offline-stream.pcm

ffmpeg -y -f f32le -ar 24000 -ac 1 -i offline-stream.pcm offline-stream.wav

afplay offline-stream.wav
```

### Notes

* The first model download requires internet.
* After bootstrap, normal runtime should be local-only.
* If the cache is deleted, run `python scripts/bootstrap_kokoro.py` again.
* The warning about unauthenticated Hugging Face requests should disappear during normal offline runtime because the app should not contact Hugging Face.

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

## Streaming

The service supports two streaming endpoints.

### Chunked WAV Streaming

```bash
curl -N -X POST http://127.0.0.1:8888/tts/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Chunk one.\nChunk two.\nChunk three.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output stream.wav
```

This endpoint streams generated WAV chunks.

Note: this may not produce one perfectly playable WAV file because each chunk has its own WAV header.

### Raw PCM Streaming

```bash
curl -N -X POST http://127.0.0.1:8888/tts/stream/pcm \
  -H "Content-Type: application/json" \
  -d '{"text":"Chunk one.\nChunk two.\nChunk three.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output stream.pcm
```

Convert to WAV:

```bash
ffmpeg -f f32le -ar 24000 -ac 1 -i stream.pcm stream.wav
```

Play on macOS:

```bash
afplay stream.wav
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |
| GET | `/runtime` | Offline/local runtime settings |
| GET | `/voices` | Example voices and defaults |
| POST | `/tts/wav` | Generate speech, return `audio/wav` |
| POST | `/tts/file` | Generate speech, save to `outputs/`, return path |
| POST | `/tts/stream` | Stream speech as chunked WAV |
| POST | `/tts/stream/pcm` | Stream speech as raw PCM (float32le) |

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
├─ models/              # Local model cache (gitignored)
├─ outputs/             # Generated WAV files
├─ scripts/             # Bootstrap, offline test, macOS helpers
└─ requirements.txt
```

## Future improvements

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
KOKORO_REPO_ID=hexgrad/Kokoro-82M
KOKORO_MODEL_DIR=models/kokoro
KOKORO_LOCAL_ONLY=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HOME=.cache/huggingface
```

See [Running Fully Local / Offline](#running-fully-local--offline) for bootstrap and offline testing.
