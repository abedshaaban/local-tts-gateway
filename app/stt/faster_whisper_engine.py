import os
from app.stt.base import STTResult


def resolve_faster_whisper_model(name: str) -> str:
    """Map Hugging Face Whisper repo IDs to faster-whisper model sizes."""
    if name.startswith("openai/whisper-"):
        return name.removeprefix("openai/whisper-")
    return name


class FasterWhisperEngine:
    name = "faster_whisper"

    def __init__(self):
        configured = os.getenv("FASTER_WHISPER_MODEL", "openai/whisper-tiny.en")
        self.model_name = resolve_faster_whisper_model(configured)
        self.device = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
        self.compute_type = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
        self.language = os.getenv("STT_LANGUAGE", "en")
        self._model = None

    def is_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(self, audio_path: str) -> STTResult:
        model = self._load_model()

        segments, info = model.transcribe(
            audio_path,
            language=self.language,
            vad_filter=True,
            beam_size=5,
        )

        text = " ".join(segment.text.strip() for segment in segments).strip()

        return {
            "text": text,
            "language": getattr(info, "language", self.language) or self.language,
            "engine_used": self.name,
        }
