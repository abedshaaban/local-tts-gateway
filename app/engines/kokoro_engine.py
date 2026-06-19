from pathlib import Path
from typing import List, Generator
import logging
import uuid

import soundfile as sf
from kokoro import KPipeline

from app.config import settings
from app.utils.audio import audio_array_to_wav_bytes, audio_array_to_pcm_bytes

logger = logging.getLogger(__name__)


class KokoroEngine:
    def __init__(self, lang_code: str = "a"):
        self.lang_code = lang_code

        try:
            self.pipeline = KPipeline(
                lang_code=lang_code,
                repo_id=settings.kokoro_repo_id,
            )
        except Exception as error:
            if settings.kokoro_local_only:
                raise RuntimeError(
                    "Failed to load Kokoro in local-only mode. "
                    "The model may not be downloaded/cached yet. "
                    "Run: python scripts/bootstrap_kokoro.py "
                    "or temporarily set KOKORO_LOCAL_ONLY=false and call /tts/wav once. "
                    f"Original error: {error}"
                ) from error

            raise

    def generate_wav_files(
        self,
        text: str,
        voice: str,
        speed: float,
        output_prefix: str | None = None,
        split_pattern: str = r"\n+",
    ) -> List[Path]:
        if not output_prefix:
            output_prefix = f"tts_{uuid.uuid4()}"

        generator = self.pipeline(
            text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

        output_files: List[Path] = []

        for index, (_graphemes, _phonemes, audio) in enumerate(generator):
            output_path = settings.output_dir / f"{output_prefix}_{index}.wav"
            sf.write(output_path, audio, settings.sample_rate)
            output_files.append(output_path)

        return output_files

    def stream_wav_chunks(
        self,
        text: str,
        voice: str,
        speed: float,
        split_pattern: str = r"\n+",
    ) -> Generator[bytes, None, None]:
        generator = self.pipeline(
            text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

        for index, (_graphemes, _phonemes, audio) in enumerate(generator):
            logger.debug("Streaming WAV chunk %s", index)
            yield audio_array_to_wav_bytes(audio)

    def stream_pcm_chunks(
        self,
        text: str,
        voice: str,
        speed: float,
        split_pattern: str = r"\n+",
    ) -> Generator[bytes, None, None]:
        generator = self.pipeline(
            text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

        for index, (_graphemes, _phonemes, audio) in enumerate(generator):
            logger.debug("Streaming PCM chunk %s", index)
            yield audio_array_to_pcm_bytes(audio)
