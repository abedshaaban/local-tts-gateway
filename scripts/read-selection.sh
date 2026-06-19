#!/bin/bash

TEXT="$1"

if [ -z "$TEXT" ]; then
  echo "No text provided."
  exit 1
fi

curl -s -X POST http://127.0.0.1:8888/tts/wav \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"$TEXT\",\"voice\":\"af_heart\",\"speed\":1,\"lang_code\":\"a\"}" \
  --output /tmp/kokoro-selected.wav

afplay /tmp/kokoro-selected.wav
