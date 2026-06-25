import os
import shutil
import tempfile
import threading
import time
from typing import Protocol

from app.config import settings
from app.model_registry import ModelRegistry, SPEECH_TO_TEXT, build_default_registry
from app.stt.base import STTResult
from app.stt.router import STTRouter
from app.utils.audio import normalize_for_stt


class STTBackend(Protocol):
    def transcribe(self, audio_path: str) -> STTResult:
        ...


class STTService:
    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or build_default_registry(settings.enabled_models)
        self.backends: dict[str, STTBackend] = {
            "local-stt-router": STTRouter(),
        }
        self.return_engine_used = (
            os.getenv("STT_RETURN_ENGINE_USED", "true").lower() == "true"
        )
        self._ffmpeg_available = shutil.which("ffmpeg") is not None
        self._transcription_lock = threading.Lock()

    def register_backend(self, provider: str, backend: STTBackend) -> None:
        self.backends[provider] = backend

    def transcribe_file(
        self,
        audio_path: str,
        model: str | None = None,
    ) -> STTResult:
        model_definition = self.registry.resolve_model(
            model or settings.default_stt_model,
            SPEECH_TO_TEXT,
        )
        backend = self.backends.get(model_definition.provider)
        if backend is None:
            raise RuntimeError(
                f"No STT backend registered for provider={model_definition.provider}"
            )
        started_at = time.time()
        normalized_path = None

        try:
            transcribe_path = audio_path

            if self._ffmpeg_available:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp:
                    normalized_path = temp.name
                normalize_for_stt(audio_path, normalized_path)
                transcribe_path = normalized_path

            with self._transcription_lock:
                result = backend.transcribe(transcribe_path)
            result["duration_seconds"] = round(time.time() - started_at, 2)

            if not self.return_engine_used:
                result.pop("engine_used", None)

            return result

        finally:
            if normalized_path and os.path.exists(normalized_path):
                os.remove(normalized_path)
