# Local TTS Gateway

A local Python/FastAPI text-to-speech and speech-to-text microservice. TTS is powered by [Kokoro](https://github.com/hexgrad/kokoro). STT uses Parakeet MLX on Apple Silicon with automatic fallback to whisper.cpp and faster-whisper.

Send text to a local API and receive generated speech as a `.wav` file, or upload audio and receive transcribed text. Useful for macOS selected text, local agents, voiceovers, and experiments.

## Architecture

```txt
Mac selected text / website / agents / scripts
        ↓
POST http://127.0.0.1:47829/tts/wav   (text → speech)
POST http://127.0.0.1:47829/stt/text  (speech → text)
        ↓
Python FastAPI service
        ↓
TTS: Kokoro engine loaded once (lazy, per language)
STT: Parakeet MLX → whisper.cpp → faster-whisper (auto fallback)
        ↓
WAV file or JSON transcript returned
```

Kokoro pipelines are loaded once and reused between requests — not reloaded on every call. STT engine selection is internal; clients do not choose the engine.

## Requirements

- Python 3.10 or 3.11 (3.12+ may work; use the same interpreter for `venv` and running the server)
- macOS (for `afplay` in the selection script)

### System dependencies

```bash
brew install espeak-ng ffmpeg
```

For STT, install at least one engine:

```bash
source .venv/bin/activate
pip install -U mlx parakeet-mlx    # recommended on Apple Silicon
pip install faster-whisper       # Python fallback
```

Optional whisper.cpp fallback (build separately):

```bash
# Set WHISPER_CPP_BIN and WHISPER_CPP_MODEL in .env after building
```

## Quick start

Use this every time you open a new terminal and want to run the server.

```bash
cd local-tts-gateway
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 47829 --reload
```

Your shell prompt should show `(.venv)` after activation. If `uvicorn` is not found, you skipped `source` — the server must run with the virtualenv's Python, not the system one.

- API: http://127.0.0.1:47829
- Docs: http://127.0.0.1:47829/docs

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

Copy STT settings into `.env` (included in `.env.example`):

```env
STT_LANGUAGE=en
STT_ENGINE_ORDER=parakeet_mlx,whisper_cpp,faster_whisper
STT_RETURN_ENGINE_USED=true
PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt-0.6b-v3
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
uvicorn app.main:app --host 127.0.0.1 --port 47829 --reload
```

### 4. Test offline WAV generation

```bash
curl -X POST http://127.0.0.1:47829/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"This is running locally without calling Hugging Face.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output offline-test.wav

afplay offline-test.wav
```

### 5. Test offline PCM streaming

```bash
curl -N -X POST http://127.0.0.1:47829/tts/stream/pcm \
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
curl http://127.0.0.1:47829/health
```

## Generate a WAV file

```bash
curl -X POST http://127.0.0.1:47829/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello Abed. Kokoro is now running locally as a TTS gateway.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output speech.wav

afplay speech.wav
```

## Speech-to-text

Upload audio and receive a JSON transcript. The engine is chosen automatically (Parakeet MLX first on Apple Silicon).

```bash
curl -X POST http://127.0.0.1:47829/stt/text \
  -F "audio=@speech.wav"
```

Example response:

```json
{
  "text": "Happy birthday to you, happy birthday to you.",
  "language": "en",
  "engine_used": "parakeet_mlx",
  "duration_seconds": 1.2
}
```

Supported upload formats: `wav`, `mp3`, `m4a`, `aac`, `flac`, `ogg`, `webm`. When `ffmpeg` is available, audio is normalized to 16 kHz mono WAV before transcription.

### STT engine priority

Configured via `STT_ENGINE_ORDER` in `.env`:

1. **parakeet_mlx** — Apple Silicon optimized (requires `parakeet-mlx` CLI)
2. **whisper_cpp** — local whisper.cpp binary + GGML model
3. **faster_whisper** — Python fallback (`small.en` by default)

Missing engines are skipped at runtime; the app does not fail on startup if a fallback is unavailable.

## Save a WAV file and return its path

```bash
curl -X POST http://127.0.0.1:47829/tts/file \
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
curl -N -X POST http://127.0.0.1:47829/tts/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Chunk one.\nChunk two.\nChunk three.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output stream.wav
```

This endpoint streams generated WAV chunks.

Note: this may not produce one perfectly playable WAV file because each chunk has its own WAV header.

### Raw PCM Streaming

```bash
curl -N -X POST http://127.0.0.1:47829/tts/stream/pcm \
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

## WebSockets

The service also supports persistent WebSocket connections for TTS and STT.

### One-shot TTS WebSocket

Connect to `ws://127.0.0.1:47829/ws/tts`, then send:

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

The server responds with a JSON `start` message describing the audio, one or
more binary PCM frames, then a JSON `complete` message. Audio is mono
`float32le` at 24 kHz. The connection stays open for additional requests.

### Incremental text-to-speech

Use this protocol when text arrives token by token from an AI model:

```json
{"type":"stream_start","request_id":"tts-live-1","voice":"af_heart","speed":1,"lang_code":"a"}
{"type":"text_delta","text":"Hello "}
{"type":"text_delta","text":"from the model. "}
{"type":"text_delta","text":"This is streamed speech."}
{"type":"end"}
```

The gateway buffers incomplete text and starts synthesis at sentence boundaries.
If no sentence boundary arrives, it flushes around `WEBSOCKET_TTS_FLUSH_CHARS`
characters. Send `{"type":"flush"}` to speak the current buffer immediately or
`{"type":"cancel"}` to stop the session.

Server messages:

- `ready` — the text stream can begin.
- `segment_start` — a buffered text segment is being synthesized.
- Binary frames — mono `float32le` PCM at 24 kHz.
- `segment_complete` — one text segment finished.
- `complete` or `cancelled` — the stream ended.
- `error` — validation or synthesis failed.

Only one incremental TTS session is active per WebSocket. The queue is bounded,
so a client naturally receives backpressure if it sends text faster than the
local model can synthesize it.

### Upload-and-transcribe STT WebSocket

Connect to `ws://127.0.0.1:47829/ws/stt`, then:

1. Send `{"type":"start","request_id":"stt-1","format":"webm"}`.
2. Wait for the JSON `ready` response.
3. Send one or more binary audio frames.
4. Send `{"type":"end"}`.
5. Receive a JSON `transcription` response.

Supported formats are `wav`, `mp3`, `m4a`, `aac`, `flac`, `ogg`, and `webm`.
Send `{"type":"abort"}` to discard an active upload. The default upload limit
is 100 MiB and can be changed with `WEBSOCKET_STT_MAX_BYTES`.

### Realtime speech-to-text

For reliable live microphone transcription, send mono signed 16-bit little
endian PCM at 16 kHz:

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

After receiving `ready`, send binary PCM frames continuously. The gateway emits:

- `speech_started` and `speech_stopped` from energy-based voice activity
  detection.
- `partial_transcript` while audio is still arriving.
- `final_transcript` after detected silence and after `{"type":"end"}`.

Partial transcript events include:

- `stable_text` — words shared with the previous revision.
- `unstable_text` — the provisional suffix that may still change.
- `window_start_ms` and `window_end_ms` — the bounded audio window used.

Send `{"type":"commit"}` to request an immediate partial transcript,
`{"type":"end"}` to finish and receive the final result, or
`{"type":"abort"}` to discard the session.

Realtime mode also accepts `wav`, `webm`, `mp3`, `m4a`, `aac`, `flac`, and
`ogg`. Partial decoding of a growing compressed container depends on whether
FFmpeg can decode the current container boundary, so raw PCM is recommended.
VAD events are available only for raw PCM.

The installed STT engines are file-oriented. Realtime mode therefore takes
periodic snapshots of the accumulated audio and retranscribes them instead of
maintaining a native decoder state. This provides live partial results while
retaining the existing Parakeet/Whisper engine fallback behavior, at the cost
of increasing work as a session grows.

Optional `start` fields:

| Field | Default | Meaning |
|---|---:|---|
| `partial_interval_ms` | `1000` | Delay between automatic partial transcripts |
| `min_audio_ms` | `500` | Audio required before automatic transcription |
| `vad_threshold` | `0.015` | Normalized PCM RMS threshold for speech |
| `vad_silence_ms` | `700` | Silence required to finalize an utterance |
| `rolling_window_ms` | `15000` | Maximum raw PCM window retranscribed for partials |

## Unified conversation WebSocket

`ws://127.0.0.1:47829/ws/conversation` combines microphone input, live
transcription, streamed TTS output, cancellation, and barge-in.

Start a session:

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

Send microphone audio as binary PCM frames. To speak a complete response:

```json
{"type":"response.create","response_id":"reply-1","text":"Hello from the assistant."}
```

For model token streams:

```json
{"type":"response.start","response_id":"reply-2"}
{"type":"response.text.delta","text":"This text "}
{"type":"response.text.delta","text":"arrives incrementally."}
{"type":"response.text.done"}
```

Important server events:

- `conversation.transcript.partial` and `conversation.transcript.final`
- `input_audio_buffer.speech_started` and `.speech_stopped`
- `response.created`, `response.audio.segment_start`, and `response.audio.done`
- `response.interrupted` when user speech cancels active TTS

Binary server frames are mono `float32le` PCM at 24 kHz. Supported controls
include `input_audio_buffer.commit`, `input_audio_buffer.clear`,
`response.flush`, `response.cancel`, and `session.end`.

## OpenAI-compatible API subset

The following local routes use OpenAI-compatible request shapes:

| Method | Path | Supported behavior |
|---|---|---|
| GET | `/v1/models` | Lists `local-tts` and `local-stt` |
| GET | `/v1/models/{id}` | Retrieves local models and accepted aliases |
| POST | `/v1/audio/speech` | `mp3`, `opus`, `aac`, `flac`, `wav`, or 24 kHz `pcm_s16le` |
| POST | `/v1/audio/transcriptions` | Multipart audio; `json`, `text`, or `verbose_json` |

Accepted speech model aliases include `tts-1`, `tts-1-hd`, and
`gpt-4o-mini-tts`. Accepted transcription aliases include `whisper-1`,
`gpt-4o-mini-transcribe`, and `gpt-4o-transcribe`. They all run the configured
local engines; they do not download or call those hosted models.

OpenAI voice names are mapped to local Kokoro voices. A native Kokoro voice
such as `af_heart` can also be passed directly. Speech `instructions`,
transcription `prompt`, and per-request language hints are accepted for client
compatibility but currently reported as ignored through response headers.

The public model name is resolved through the gateway model registry before a
local backend is selected. OpenAI model names are aliases, not hosted model
downloads. The default catalog maps TTS aliases to the Kokoro backend and STT
aliases to the configured local STT router.

Example:

```bash
curl http://127.0.0.1:47829/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1","voice":"alloy","input":"Local speech.","response_format":"mp3"}' \
  --output speech.mp3

curl http://127.0.0.1:47829/v1/audio/transcriptions \
  -F model=whisper-1 \
  -F file=@speech.mp3
```

## ElevenLabs-compatible API subset

The gateway also exposes the common ElevenLabs TTS and voice-discovery shapes:

| Method | Path | Supported behavior |
|---|---|---|
| POST | `/v1/text-to-speech/{voice_id}` | Generate speech using an ElevenLabs-style request |
| POST | `/v1/text-to-speech/{voice_id}/stream` | Stream the generated audio response |
| GET | `/v1/voices` and `/v2/voices` | List local voices with pagination fields |
| GET | `/v1/voices/{voice_id}` | Retrieve a local voice or accepted alias |
| GET | `/elevenlabs/v1/models` | ElevenLabs-shaped local TTS model list |

`/elevenlabs/v1/models` is namespaced because OpenAI and ElevenLabs both define
`GET /v1/models` with incompatible response schemas. The OpenAI shape remains
at `/v1/models`.

Example:

```bash
curl "http://127.0.0.1:47829/v1/text-to-speech/alloy?output_format=mp3_44100_128" \
  -H "Content-Type: application/json" \
  -d '{"text":"Local speech.","model_id":"eleven_multilingual_v2"}' \
  --output speech.mp3
```

## Model and backend architecture

Routes do not instantiate engines directly. They resolve a model and voice
through `app/model_registry.py`, then the TTS or STT service dispatches to the
registered provider backend.

The default catalog contains:

- `local-tts` using provider `kokoro`
- `local-stt` using provider `local-stt-router`

Aliases such as `gpt-4o-mini-tts`, `whisper-1`, and
`eleven_multilingual_v2` resolve to those canonical local models.

Configure which canonical models are active without changing routes:

```env
DEFAULT_TTS_MODEL=local-tts
DEFAULT_STT_MODEL=local-stt
ENABLED_MODELS=local-tts,local-stt
```

To add another local model later:

1. Implement or register its provider backend in the relevant service.
2. Add one `ModelDefinition` to `build_default_registry()`.
3. Add its voices, aliases, and capabilities to the registry.

No runtime model-management API is exposed. Model availability remains an
operator-controlled deployment setting.

## Client SDKs

### TypeScript/browser

```bash
cd sdk/typescript
npm install
npm run build
```

```ts
import { LocalTTSGateway } from "@local-tts-gateway/client";

const gateway = new LocalTTSGateway();
const conversation = gateway.conversation({
  onEvent: (event) => console.log(event),
});

await conversation.connect();
await conversation.startMicrophone();
conversation.createResponse("The gateway can speak this response.");
```

The browser client performs microphone capture, downsampling to 16 kHz
`pcm_s16le`, PCM playback, interruption cleanup, cancellation, and reconnects.
Browser HTTP calls are allowed by default from `localhost`, `127.0.0.1`, and
local `file://` pages. Override `CORS_ALLOW_ORIGIN_REGEX` when integrating a
different local origin.

### Python

```bash
pip install -e sdk/python
```

```python
from local_tts_gateway import LocalTTSGateway

gateway = LocalTTSGateway()
audio = gateway.speech("Hello locally.", response_format="wav")
open("speech.wav", "wb").write(audio)
print(gateway.transcribe("speech.wav"))
```

`ConversationClient` provides async unified-WebSocket events, binary audio
input/output, response text streaming, and reconnect behavior.

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
| POST | `/stt/text` | Transcribe uploaded audio, return JSON |
| WS | `/ws/tts` | One-shot or incremental-text TTS with streamed PCM output |
| WS | `/ws/stt` | Upload audio or receive live partial/final transcripts |
| WS | `/ws/conversation` | Unified STT/TTS session with barge-in |
| GET/POST | `/v1/*` | OpenAI-compatible models and audio subset |
| GET/POST | `/v1/text-to-speech/*`, `/v1/voices*` | ElevenLabs-compatible TTS subset |

## Tests

Run the full suite with individual test names and a final pass/fail overview:

```bash
make test
```

`make tests` is an alias. Running `make test tests` still executes the suite
only once. To compile-check the application, run tests, and type-check both
SDKs:

```bash
make local
```

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
│  ├─ stt/              # STT engines and router
│  ├─ services/         # Business logic (TTS + STT)
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
APP_PORT=47829
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

STT_LANGUAGE=en
STT_ENGINE_ORDER=parakeet_mlx,whisper_cpp,faster_whisper
STT_RETURN_ENGINE_USED=true
PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt-0.6b-v3
WHISPER_CPP_BIN=./vendor/whisper.cpp/build/bin/whisper-cli
WHISPER_CPP_MODEL=./models/whisper/ggml-large-v3-turbo.bin
FASTER_WHISPER_MODEL=small.en
FASTER_WHISPER_DEVICE=cpu
FASTER_WHISPER_COMPUTE_TYPE=int8
```

See [Running Fully Local / Offline](#running-fully-local--offline) for bootstrap and offline testing.
