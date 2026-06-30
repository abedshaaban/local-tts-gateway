#!/bin/bash

set -euo pipefail

TEXT="${1:-}"
HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-47829}"
VOICE="${VOICE:-af_heart}"
LANG_CODE="${LANG_CODE:-a}"
OUTPUT_FILE="${OUTPUT_FILE:-/tmp/local-speech-gateway-selection.wav}"

if [ -z "$TEXT" ]; then
  echo "No text provided."
  exit 1
fi

PAYLOAD="$(
  TEXT="$TEXT" VOICE="$VOICE" LANG_CODE="$LANG_CODE" python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "text": os.environ["TEXT"],
            "voice": os.environ["VOICE"],
            "speed": 1,
            "lang_code": os.environ["LANG_CODE"],
        }
    )
)
PY
)"

curl -fsS -X POST "http://${HOST}:${PORT}/tts/wav" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  --output "$OUTPUT_FILE"

afplay "$OUTPUT_FILE"
