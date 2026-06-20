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

test_tts() {
  curl -X POST "http://${HOST}:${PORT}/tts/wav" \
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

  curl -s -X POST "http://${HOST}:${PORT}/stt/text" \
    -F "audio=@speech.wav" | jq
}

case "$1" in
  install)
    install_deps
    ;;

  dev)
    dev_server
    ;;

  start)
    start_server
    ;;

  check)
    check_app
    ;;

  test-tts)
    test_tts
    ;;

  test-stt)
    test_stt
    ;;

  *)
    echo "Usage:"
    echo "  ./scripts/server.sh install    Install Python dependencies"
    echo "  ./scripts/server.sh dev        Start FastAPI server with reload"
    echo "  ./scripts/server.sh start      Start FastAPI server without reload"
    echo "  ./scripts/server.sh check      Compile-check Python files"
    echo "  ./scripts/server.sh test-tts   Generate speech.wav from TTS endpoint"
    echo "  ./scripts/server.sh test-stt   Send speech.wav to STT endpoint"
    exit 1
    ;;
esac
