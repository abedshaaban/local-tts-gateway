import os
from app.stt.parakeet_mlx_engine import ParakeetMLXEngine
from app.stt.whisper_cpp_engine import WhisperCppEngine
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.base import STTResult


ENGINE_FACTORIES = {
    "parakeet_mlx": ParakeetMLXEngine,
    "whisper_cpp": WhisperCppEngine,
    "faster_whisper": FasterWhisperEngine,
}


class STTRouter:
    def __init__(self):
        order = os.getenv(
            "STT_ENGINE_ORDER",
            "parakeet_mlx,whisper_cpp,faster_whisper",
        )

        self.engines = []
        for name in [item.strip() for item in order.split(",") if item.strip()]:
            factory = ENGINE_FACTORIES.get(name)
            if factory:
                self.engines.append(factory())

    def transcribe(self, audio_path: str) -> STTResult:
        errors = []

        for engine in self.engines:
            try:
                if not engine.is_available():
                    errors.append({"engine": engine.name, "error": "not available"})
                    continue

                result = engine.transcribe(audio_path)
                result["engine_used"] = engine.name
                return result

            except Exception as error:
                errors.append({"engine": engine.name, "error": str(error)})

        raise RuntimeError(f"No STT engine worked. Errors: {errors}")
