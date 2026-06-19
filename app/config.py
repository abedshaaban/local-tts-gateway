from pathlib import Path
from pydantic import BaseModel
import os


class Settings(BaseModel):
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8888"))

    default_lang_code: str = os.getenv("DEFAULT_LANG_CODE", "a")
    default_voice: str = os.getenv("DEFAULT_VOICE", "af_heart")
    default_speed: float = float(os.getenv("DEFAULT_SPEED", "1.0"))

    sample_rate: int = 24000

    base_dir: Path = Path(__file__).resolve().parent.parent
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "outputs"))


settings = Settings()

settings.output_dir.mkdir(parents=True, exist_ok=True)
