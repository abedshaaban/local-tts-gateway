import logging
import uuid
from pathlib import Path
from typing import Generator, Protocol

from app.config import settings
from app.engines.kokoro_engine import KokoroEngine
from app.model_registry import ModelRegistry, TEXT_TO_SPEECH, build_default_registry
from app.utils.audio import combine_wav_files

logger = logging.getLogger(__name__)


class TTSBackend(Protocol):
    def generate_wav(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Path:
        ...

    def stream_wav(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Generator[bytes, None, None]:
        ...

    def stream_pcm(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Generator[bytes, None, None]:
        ...


class KokoroTTSBackend:
    def __init__(self) -> None:
        self.engines: dict[str, KokoroEngine] = {}

    def get_engine(self, lang_code: str) -> KokoroEngine:
        if lang_code not in self.engines:
            logger.info("Loading Kokoro engine for lang_code=%s", lang_code)
            self.engines[lang_code] = KokoroEngine(lang_code=lang_code)
        return self.engines[lang_code]

    def generate_wav(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Path:
        engine = self.get_engine(lang_code)
        output_prefix = f"tts_{uuid.uuid4()}"
        chunk_files = engine.generate_wav_files(
            text=text,
            voice=voice,
            speed=speed,
            output_prefix=output_prefix,
            split_pattern=split_pattern,
        )
        final_output = settings.output_dir / f"{output_prefix}.wav"
        return combine_wav_files(chunk_files, final_output)

    def stream_wav(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Generator[bytes, None, None]:
        yield from self.get_engine(lang_code).stream_wav_chunks(
            text=text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

    def stream_pcm(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ) -> Generator[bytes, None, None]:
        yield from self.get_engine(lang_code).stream_pcm_chunks(
            text=text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )


class TTSService:
    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or build_default_registry(settings.enabled_models)
        self.backends: dict[str, TTSBackend] = {}
        self.register_backend("kokoro", KokoroTTSBackend())

    def register_backend(self, provider: str, backend: TTSBackend) -> None:
        self.backends[provider] = backend

    def resolve(self, model: str | None, voice: str):
        model_definition = self.registry.resolve_model(
            model or settings.default_tts_model,
            TEXT_TO_SPEECH,
        )
        voice_definition = self.registry.resolve_voice(
            voice,
            model_definition.id,
        )
        backend = self.backends.get(model_definition.provider)
        if backend is None:
            raise RuntimeError(
                f"No TTS backend registered for provider={model_definition.provider}"
            )
        return backend, voice_definition

    def generate_wav(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
        model: str | None = None,
    ) -> Path:
        backend, voice_definition = self.resolve(model, voice)
        return backend.generate_wav(
            text=text,
            voice=voice_definition.id,
            speed=speed,
            lang_code=lang_code,
            split_pattern=split_pattern,
        )

    def stream_wav(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
        model: str | None = None,
    ) -> Generator[bytes, None, None]:
        backend, voice_definition = self.resolve(model, voice)
        yield from backend.stream_wav(
            text=text,
            voice=voice_definition.id,
            speed=speed,
            lang_code=lang_code,
            split_pattern=split_pattern,
        )

    def stream_pcm(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
        model: str | None = None,
    ) -> Generator[bytes, None, None]:
        backend, voice_definition = self.resolve(model, voice)
        yield from backend.stream_pcm(
            text=text,
            voice=voice_definition.id,
            speed=speed,
            lang_code=lang_code,
            split_pattern=split_pattern,
        )
