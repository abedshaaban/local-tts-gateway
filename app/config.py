from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.lower() in {"1", "true", "yes", "y", "on"}


class Settings(BaseModel):
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8888"))

    default_lang_code: str = os.getenv("DEFAULT_LANG_CODE", "a")
    default_voice: str = os.getenv("DEFAULT_VOICE", "af_heart")
    default_speed: float = float(os.getenv("DEFAULT_SPEED", "1.0"))

    sample_rate: int = 24000

    base_dir: Path = Path(__file__).resolve().parent.parent
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "outputs"))

    kokoro_repo_id: str = os.getenv("KOKORO_REPO_ID", "hexgrad/Kokoro-82M")
    kokoro_model_dir: Path = Path(os.getenv("KOKORO_MODEL_DIR", "models/kokoro"))
    kokoro_local_only: bool = str_to_bool(os.getenv("KOKORO_LOCAL_ONLY"), True)

    hf_home: Path = Path(os.getenv("HF_HOME", ".cache/huggingface"))


settings = Settings()

settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.kokoro_model_dir.mkdir(parents=True, exist_ok=True)
settings.hf_home.mkdir(parents=True, exist_ok=True)
