import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.stt.faster_whisper_engine import resolve_faster_whisper_model

# Online bootstrap mode.
os.environ["HF_HOME"] = str(settings.hf_home)
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)


def main():
    configured = os.getenv("FASTER_WHISPER_MODEL", "openai/whisper-tiny.en")
    model_name = resolve_faster_whisper_model(configured)
    device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")

    print("[bootstrap] Downloading/caching faster-whisper model...")
    print(f"[bootstrap] configured: {configured}")
    print(f"[bootstrap] resolved:   {model_name}")
    print(f"[bootstrap] HF_HOME:    {settings.hf_home}")

    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(ROOT_DIR / "speech.wav"),
        language=os.getenv("STT_LANGUAGE", "en"),
        vad_filter=True,
        beam_size=1,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()

    print(f"[bootstrap] Warmup transcription: {text!r}")
    print(f"[bootstrap] Detected language: {getattr(info, 'language', 'unknown')}")
    print("[bootstrap] Done. faster-whisper should now be cached locally.")


if __name__ == "__main__":
    main()
