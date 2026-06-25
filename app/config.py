from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.lower() in {"1", "true", "yes", "y", "on"}


def csv_to_set(value: str | None, default: str) -> set[str]:
    return {
        item.strip()
        for item in (value if value is not None else default).split(",")
        if item.strip()
    }


class Settings(BaseModel):
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "47829"))

    default_lang_code: str = os.getenv("DEFAULT_LANG_CODE", "a")
    default_voice: str = os.getenv("DEFAULT_VOICE", "af_heart")
    default_speed: float = float(os.getenv("DEFAULT_SPEED", "1.0"))
    default_tts_model: str = os.getenv("DEFAULT_TTS_MODEL", "local-tts")
    default_stt_model: str = os.getenv("DEFAULT_STT_MODEL", "local-stt")
    enabled_models: set[str] = csv_to_set(
        os.getenv("ENABLED_MODELS"),
        "local-tts,local-stt",
    )

    sample_rate: int = 24000
    websocket_stt_max_bytes: int = int(
        os.getenv("WEBSOCKET_STT_MAX_BYTES", str(100 * 1024 * 1024))
    )
    websocket_stt_partial_interval_ms: int = int(
        os.getenv("WEBSOCKET_STT_PARTIAL_INTERVAL_MS", "1000")
    )
    websocket_stt_min_audio_ms: int = int(
        os.getenv("WEBSOCKET_STT_MIN_AUDIO_MS", "500")
    )
    websocket_stt_vad_threshold: float = float(
        os.getenv("WEBSOCKET_STT_VAD_THRESHOLD", "0.015")
    )
    websocket_stt_vad_silence_ms: int = int(
        os.getenv("WEBSOCKET_STT_VAD_SILENCE_MS", "700")
    )
    websocket_stt_rolling_window_ms: int = int(
        os.getenv("WEBSOCKET_STT_ROLLING_WINDOW_MS", "15000")
    )
    websocket_tts_max_buffer_chars: int = int(
        os.getenv("WEBSOCKET_TTS_MAX_BUFFER_CHARS", "4000")
    )
    websocket_tts_flush_chars: int = int(
        os.getenv("WEBSOCKET_TTS_FLUSH_CHARS", "240")
    )
    conversation_barge_in: bool = str_to_bool(
        os.getenv("CONVERSATION_BARGE_IN"),
        True,
    )
    cors_allow_origin_regex: str = os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|null)$",
    )

    base_dir: Path = Path(__file__).resolve().parent.parent
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "outputs"))
    save_generated_audio: bool = str_to_bool(
        os.getenv("SAVE_GENERATED_AUDIO"),
        False,
    )
    save_transcriptions: bool = str_to_bool(
        os.getenv("SAVE_TRANSCRIPTIONS"),
        False,
    )

    kokoro_repo_id: str = os.getenv("KOKORO_REPO_ID", "hexgrad/Kokoro-82M")
    kokoro_model_dir: Path = Path(os.getenv("KOKORO_MODEL_DIR", "models/kokoro"))
    kokoro_local_only: bool = str_to_bool(os.getenv("KOKORO_LOCAL_ONLY"), True)

    hf_home: Path = Path(os.getenv("HF_HOME", ".cache/huggingface"))


settings = Settings()

settings.output_dir.mkdir(parents=True, exist_ok=True)
if settings.save_transcriptions:
    (settings.output_dir / "transcriptions").mkdir(parents=True, exist_ok=True)
settings.kokoro_model_dir.mkdir(parents=True, exist_ok=True)
settings.hf_home.mkdir(parents=True, exist_ok=True)
