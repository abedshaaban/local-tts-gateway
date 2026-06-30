# Local Speech Gateway

A local FastAPI gateway for text-to-speech and speech-to-text.

- **TTS:** Kokoro, loaded lazily and reused per language.
- **STT:** automatic local fallback order across Parakeet MLX, whisper.cpp, and faster-whisper.
- **Compatibility APIs:** local OpenAI-style audio routes and ElevenLabs-style TTS routes.
- **Realtime:** WebSocket TTS, upload STT, realtime STT snapshots, and a combined conversation socket.

The service is designed for local macOS workflows such as reading selected text, local agents, voice experiments, and offline speech generation after models are cached.

## Requirements

- Python 3.10 or 3.11
- macOS for the included `afplay` helper scripts
- `espeak-ng` for Kokoro
- `ffmpeg` for audio conversion and STT normalization

```bash
brew install espeak-ng ffmpeg
```

## Setup

```bash
git clone <your-repo-url> local-tts-gateway
cd local-tts-gateway
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/bootstrap_kokoro.py
```

Start the server:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 47829 --reload
```

Useful URLs:

- API root: `http://127.0.0.1:47829`
- API docs: `http://127.0.0.1:47829/docs`
- Health check: `http://127.0.0.1:47829/health`

You can also use the Makefile:

```bash
make install
make dev
make test
```

## Optional STT Engines

Install at least one STT backend if you want transcription.

Apple Silicon recommended backend:

```bash
pip install -r requirements-stt-apple-silicon.txt
```

Python fallback backend:

```bash
pip install -r requirements-stt-faster-whisper.txt
```

Optional whisper.cpp backend is configured by pointing the gateway at your local binary and model:

```env
WHISPER_CPP_BIN=./vendor/whisper.cpp/build/bin/whisper-cli
WHISPER_CPP_MODEL=./models/whisper/ggml-large-v3-turbo.bin
```

Default STT priority is:

```env
STT_ENGINE_ORDER=parakeet_mlx,whisper_cpp,faster_whisper
```

Missing engines are skipped at runtime. The app starts as long as the core dependencies are installed.

## Configuration

Copy `.env.example` to `.env` and adjust values as needed.

Common settings:

```env
APP_HOST=127.0.0.1
APP_PORT=47829
DEFAULT_VOICE=af_heart
DEFAULT_LANG_CODE=a
DEFAULT_TTS_MODEL=local-tts
DEFAULT_STT_MODEL=local-stt
OUTPUT_DIR=outputs
SAVE_GENERATED_AUDIO=false
SAVE_TRANSCRIPTIONS=false
```

Offline/local-cache settings:

```env
KOKORO_LOCAL_ONLY=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HOME=.cache/huggingface
KOKORO_REPO_ID=hexgrad/Kokoro-82M
```

Generated files, model folders, `.env`, cache folders, and virtualenv files are ignored by Git.

## Offline Mode

Bootstrap Kokoro once while online:

```bash
source .venv/bin/activate
python scripts/bootstrap_kokoro.py
```

Then keep these values in `.env`:

```env
KOKORO_LOCAL_ONLY=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HOME=.cache/huggingface
```

Start the server and test:

```bash
./scripts/test_offline.sh
```

If you delete the cache, run `python scripts/bootstrap_kokoro.py` again while connected to the internet.

## Core HTTP API

Health:

```bash
curl http://127.0.0.1:47829/health
```

List voices:

```bash
curl http://127.0.0.1:47829/voices
```

Generate a WAV response:

```bash
curl -X POST http://127.0.0.1:47829/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello from the local speech gateway.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output speech.wav
```

Save a WAV under `OUTPUT_DIR` and return its path:

```bash
curl -X POST http://127.0.0.1:47829/tts/file \
  -H "Content-Type: application/json" \
  -d '{"text":"Save this speech file.","voice":"af_heart","speed":1,"lang_code":"a"}'
```

Transcribe audio:

```bash
curl -X POST http://127.0.0.1:47829/stt/text \
  -F "audio=@speech.wav"
```

Supported upload formats: `wav`, `mp3`, `m4a`, `aac`, `flac`, `ogg`, and `webm`.

## Streaming TTS

Chunked WAV stream:

```bash
curl -N -X POST http://127.0.0.1:47829/tts/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Chunk one.\nChunk two.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output stream.wav
```

Raw PCM stream:

```bash
curl -N -X POST http://127.0.0.1:47829/tts/stream/pcm \
  -H "Content-Type: application/json" \
  -d '{"text":"Chunk one.\nChunk two.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output stream.pcm

ffmpeg -f f32le -ar 24000 -ac 1 -i stream.pcm stream.wav
```

PCM streams are mono `float32le` at 24 kHz.

## WebSockets

The gateway exposes three WebSocket routes:

| Route | Purpose |
|---|---|
| `/ws/tts` | one-shot and incremental TTS |
| `/ws/stt` | upload STT and realtime STT snapshots |
| `/ws/conversation` | microphone input, transcript events, streamed TTS, and barge-in |

One-shot TTS message:

```json
{
  "type": "synthesize",
  "request_id": "tts-1",
  "text": "Hello from WebSockets.",
  "voice": "af_heart",
  "speed": 1,
  "lang_code": "a"
}
```

Incremental TTS messages:

```json
{"type":"stream_start","request_id":"tts-live-1","voice":"af_heart","speed":1,"lang_code":"a"}
{"type":"text_delta","text":"Hello "}
{"type":"text_delta","text":"from the model."}
{"type":"end"}
```

Realtime STT start message:

```json
{
  "type": "start",
  "request_id": "stt-live-1",
  "format": "pcm_s16le",
  "sample_rate": 16000,
  "channels": 1,
  "realtime": true
}
```

Conversation start message:

```json
{
  "type": "session.start",
  "config": {
    "format": "pcm_s16le",
    "sample_rate": 16000,
    "channels": 1,
    "barge_in": true,
    "voice": "af_heart"
  }
}
```

Binary audio sent to `/ws/stt` and `/ws/conversation` should be mono signed 16-bit little-endian PCM at 16 kHz for the most reliable realtime behavior. Binary audio returned by TTS sockets is mono `float32le` PCM at 24 kHz.

## OpenAI-Compatible Audio Routes

These routes use OpenAI-style request and response shapes while running only local backends.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/models` | lists local model IDs |
| `GET` | `/v1/models/{id}` | resolves local IDs and aliases |
| `POST` | `/v1/audio/speech` | returns `mp3`, `opus`, `aac`, `flac`, `wav`, or `pcm` |
| `POST` | `/v1/audio/transcriptions` | returns `json`, `text`, or `verbose_json` |

Accepted TTS aliases include `tts-1`, `tts-1-hd`, and `gpt-4o-mini-tts`.
Accepted STT aliases include `whisper-1`, `gpt-4o-mini-transcribe`, and `gpt-4o-transcribe`.

Example:

```bash
curl -X POST http://127.0.0.1:47829/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1","voice":"alloy","input":"Local speech.","response_format":"mp3"}' \
  --output speech.mp3

curl -X POST http://127.0.0.1:47829/v1/audio/transcriptions \
  -F model=whisper-1 \
  -F file=@speech.mp3
```

OpenAI voice names are mapped to Kokoro voices. Native Kokoro voice IDs such as `af_heart` are also accepted.

## ElevenLabs-Compatible TTS Routes

These routes support common ElevenLabs TTS and voice-discovery shapes while running local Kokoro voices.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/text-to-speech/{voice_id}` | generate speech |
| `POST` | `/v1/text-to-speech/{voice_id}/stream` | stream generated speech |
| `GET` | `/v1/voices` and `/v2/voices` | list local voices |
| `GET` | `/v1/voices/{voice_id}` | resolve local voice IDs and aliases |
| `GET` | `/elevenlabs/v1/models` | ElevenLabs-shaped local model list |

`/elevenlabs/v1/models` is namespaced because OpenAI and ElevenLabs both define `GET /v1/models` with different response schemas.

Example:

```bash
curl "http://127.0.0.1:47829/v1/text-to-speech/alloy?output_format=mp3_44100_128" \
  -H "Content-Type: application/json" \
  -d '{"text":"Local ElevenLabs-compatible speech.","model_id":"eleven_multilingual_v2"}' \
  --output speech.mp3
```

## Python SDK

The local SDK lives in `sdk/python`.

```bash
pip install -e sdk/python
```

```python
from local_speech_gateway import LocalSpeechGateway

client = LocalSpeechGateway("http://127.0.0.1:47829")

audio = client.speech(
    "Hello from the Python SDK.",
    model="tts-1",
    voice="alloy",
    response_format="wav",
)

with open("speech.wav", "wb") as file:
    file.write(audio)

print(client.transcribe("speech.wav", model="whisper-1"))
```

The older `local_tts_gateway` import path is still available as a compatibility alias.

## Scripts

| Command | Purpose |
|---|---|
| `./scripts/server.sh install` | install core dependencies |
| `./scripts/server.sh dev` | run Uvicorn with reload |
| `./scripts/server.sh start` | run Uvicorn without reload |
| `./scripts/server.sh check` | compile-check app, scripts, and SDK |
| `./scripts/server.sh test` | run the unittest suite |
| `./scripts/server.sh health` | call `/health` |
| `./scripts/server.sh test-tts` | generate `speech.wav` |
| `./scripts/server.sh test-stt` | transcribe `speech.wav` |
| `./scripts/read-selection.sh "text"` | synthesize text and play it with `afplay` |

## Development Checks

```bash
source .venv/bin/activate
python -m compileall app scripts sdk/python
python -m unittest discover -v
```

The test suite mocks model calls, so it can validate routing, compatibility shapes, retention behavior, SDK helpers, and WebSocket protocols without generating real audio.
