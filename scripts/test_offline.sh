#!/bin/bash

set -euo pipefail

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-47829}"
OUTPUT_FILE="${OUTPUT_FILE:-offline-test.wav}"

export KOKORO_LOCAL_ONLY=true
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME=.cache/huggingface

echo "[offline-test] Testing /tts/wav in offline mode..."

curl -fsS -X POST "http://${HOST}:${PORT}/tts/wav" \
  -H "Content-Type: application/json" \
  -d '{"text":"This is an offline local Kokoro test.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output "$OUTPUT_FILE"

echo "[offline-test] Generated $OUTPUT_FILE"
ls -lh "$OUTPUT_FILE"

if command -v afplay >/dev/null 2>&1; then
  afplay "$OUTPUT_FILE"
fi
