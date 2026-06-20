#!/bin/bash

set -e

export KOKORO_LOCAL_ONLY=true
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME=.cache/huggingface

echo "[offline-test] Testing /tts/wav in offline mode..."

curl -X POST http://127.0.0.1:47829/tts/wav \
  -H "Content-Type: application/json" \
  -d '{"text":"This is an offline local Kokoro test.","voice":"af_heart","speed":1,"lang_code":"a"}' \
  --output offline-test.wav

echo "[offline-test] Generated offline-test.wav"
ls -lh offline-test.wav

if command -v afplay >/dev/null 2>&1; then
  afplay offline-test.wav
fi
