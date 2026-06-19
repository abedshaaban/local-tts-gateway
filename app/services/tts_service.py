from pathlib import Path
import uuid

from app.config import settings
from app.engines.kokoro_engine import KokoroEngine
from app.utils.audio import combine_wav_files


class TTSService:
    def __init__(self):
        self.engines: dict[str, KokoroEngine] = {}

    def get_engine(self, lang_code: str) -> KokoroEngine:
        if lang_code not in self.engines:
            self.engines[lang_code] = KokoroEngine(lang_code=lang_code)

        return self.engines[lang_code]

    def generate_wav(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
    ) -> Path:
        engine = self.get_engine(lang_code)

        file_id = str(uuid.uuid4())
        output_prefix = f"tts_{file_id}"

        chunk_files = engine.generate_wav_files(
            text=text,
            voice=voice,
            speed=speed,
            output_prefix=output_prefix,
        )

        final_output = settings.output_dir / f"{output_prefix}.wav"

        return combine_wav_files(chunk_files, final_output)
