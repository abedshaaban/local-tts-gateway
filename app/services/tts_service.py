from pathlib import Path
from typing import Generator
import logging
import uuid

from app.config import settings
from app.engines.kokoro_engine import KokoroEngine
from app.utils.audio import combine_wav_files

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self):
        self.engines: dict[str, KokoroEngine] = {}

    def get_engine(self, lang_code: str) -> KokoroEngine:
        if lang_code not in self.engines:
            logger.info("Loading Kokoro engine for lang_code=%s", lang_code)
            self.engines[lang_code] = KokoroEngine(lang_code=lang_code)

        return self.engines[lang_code]

    def generate_wav(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
    ) -> Path:
        engine = self.get_engine(lang_code)

        file_id = str(uuid.uuid4())
        output_prefix = f"tts_{file_id}"

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
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
    ) -> Generator[bytes, None, None]:
        engine = self.get_engine(lang_code)

        yield from engine.stream_wav_chunks(
            text=text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

    def stream_pcm(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        split_pattern: str = r"\n+",
    ) -> Generator[bytes, None, None]:
        engine = self.get_engine(lang_code)

        yield from engine.stream_pcm_chunks(
            text=text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )
