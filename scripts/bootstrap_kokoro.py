import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import settings

# Online bootstrap mode.
os.environ["HF_HOME"] = str(settings.hf_home)
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)

from kokoro import KPipeline


def main():
    print("[bootstrap] Downloading/caching Kokoro model...")
    print(f"[bootstrap] repo_id: {settings.kokoro_repo_id}")
    print(f"[bootstrap] HF_HOME: {settings.hf_home}")

    pipeline = KPipeline(
        lang_code=settings.default_lang_code,
        repo_id=settings.kokoro_repo_id,
    )

    generator = pipeline(
        "Bootstrap test. This downloads and warms up Kokoro locally.",
        voice=settings.default_voice,
        speed=settings.default_speed,
        split_pattern=r"\n+",
    )

    for index, (_graphemes, _phonemes, _audio) in enumerate(generator):
        print(f"[bootstrap] Generated test chunk {index}")

    print("[bootstrap] Done. Kokoro should now be cached locally.")


if __name__ == "__main__":
    main()
