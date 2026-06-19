import os
import shutil
import tempfile
import time
from app.stt.router import STTRouter
from app.stt.base import STTResult
from app.utils.audio import normalize_for_stt


class STTService:
    def __init__(self):
        self.router = STTRouter()
        self.return_engine_used = os.getenv("STT_RETURN_ENGINE_USED", "true").lower() == "true"
        self._ffmpeg_available = shutil.which("ffmpeg") is not None

    def transcribe_file(self, audio_path: str) -> STTResult:
        started_at = time.time()
        normalized_path = None

        try:
            transcribe_path = audio_path

            if self._ffmpeg_available:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp:
                    normalized_path = temp.name
                normalize_for_stt(audio_path, normalized_path)
                transcribe_path = normalized_path

            result = self.router.transcribe(transcribe_path)
            result["duration_seconds"] = round(time.time() - started_at, 2)

            if not self.return_engine_used:
                result.pop("engine_used", None)

            return result

        finally:
            if normalized_path and os.path.exists(normalized_path):
                os.remove(normalized_path)
