#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

APP_MODULE="app.main:app"
VENV_DIR=".venv"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

HOST="${HOST:-${APP_HOST:-127.0.0.1}}"
PORT="${PORT:-${APP_PORT:-8888}}"
BASE_URL="http://${HOST}:${PORT}"

activate_venv() {
  if [ -d "$VENV_DIR" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
  else
    echo "❌ Virtual environment not found: $VENV_DIR"
    echo "Run: python3.11 -m venv .venv"
    exit 1
  fi
}

install_deps() {
  activate_venv
  python -m pip install --upgrade pip
  pip install -r requirements.txt
}

dev_server() {
  activate_venv
  uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT" --reload
}

start_server() {
  activate_venv
  uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT"
}

check_app() {
  activate_venv
  python -m compileall app
}

health() {
  curl -s "${BASE_URL}/health" | jq
}

test_tts() {
  curl -X POST "${BASE_URL}/tts/wav" \
    -H "Content-Type: application/json" \
    -d '{"text":"Hello, this is a local TTS gateway test.","voice":"af_heart","speed":1.0,"lang_code":"a"}' \
    --output speech.wav

  echo ""
  echo "✅ TTS test complete. Output saved to speech.wav"
}

test_stt() {
  if [ ! -f "speech.wav" ]; then
    echo "❌ speech.wav not found."
    echo "Create one first, or run: ./scripts/server.sh test-tts"
    exit 1
  fi

  curl -s -X POST "${BASE_URL}/stt/text" \
    -F "audio=@speech.wav" | jq
}

record_stt() {
  DURATION="${2:-7}"
  AUDIO_FILE="speech.wav"

  if ! command -v rec >/dev/null 2>&1; then
    echo "❌ 'rec' command not found."
    echo "Install it with: brew install sox"
    exit 1
  fi

  echo "🎙️ Recording for ${DURATION} seconds..."
  rec -q -r 16000 -c 1 -b 16 "$AUDIO_FILE" trim 0 "$DURATION"

  echo "🧠 Transcribing..."
  curl -s -X POST "${BASE_URL}/stt/text" \
    -F "audio=@${AUDIO_FILE}" | jq -r '.text'
}

cache_stt() {
  activate_venv

  echo "🌐 Temporarily allowing online model access for STT cache test..."
  export HF_HUB_OFFLINE=0
  export TRANSFORMERS_OFFLINE=0

  if command -v parakeet-mlx >/dev/null 2>&1; then
    echo "Testing Parakeet MLX..."
    if [ ! -f "speech.wav" ]; then
      echo "Creating test speech.wav using TTS endpoint first..."
      test_tts
    fi

    parakeet-mlx speech.wav --model "${PARAKEET_MLX_MODEL:-mlx-community/parakeet-tdt-0.6b-v3}"
  else
    echo "⚠️ parakeet-mlx not found."
    echo "Install it with: pip install parakeet-mlx"
  fi
}

case "$1" in
  install)
    install_deps
    ;;

  dev)
    dev_server
    ;;

  start | serve | prod)
    start_server
    ;;

  check | build)
    check_app
    ;;

  health)
    health
    ;;

  test-tts)
    test_tts
    ;;

  test-stt)
    test_stt
    ;;

  record-stt)
    record_stt "$@"
    ;;

  cache-stt)
    cache_stt
    ;;

  *)
    echo "Usage:"
    echo "  ./scripts/server.sh install          Install Python dependencies"
    echo "  ./scripts/server.sh dev              Start FastAPI server with reload"
    echo "  ./scripts/server.sh start            Start FastAPI server without reload"
    echo "  ./scripts/server.sh serve            Same as start"
    echo "  ./scripts/server.sh prod             Same as start"
    echo "  ./scripts/server.sh check            Compile-check Python files"
    echo "  ./scripts/server.sh build            Same as check"
    echo "  ./scripts/server.sh health           Check API health endpoint"
    echo "  ./scripts/server.sh test-tts         Generate speech.wav from TTS endpoint"
    echo "  ./scripts/server.sh test-stt         Send speech.wav to STT endpoint"
    echo "  ./scripts/server.sh record-stt 7     Record 7 seconds and transcribe"
    echo "  ./scripts/server.sh cache-stt        Download/test STT model cache"
    exit 1
    ;;
esac