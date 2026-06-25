import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.stt_service import STTService


class OutputRetentionTests(unittest.TestCase):
    def test_transcription_is_saved_as_json_when_enabled(self):
        class Backend:
            def transcribe(self, _audio_path):
                return {
                    "text": "saved transcript",
                    "language": "en",
                    "engine_used": "test",
                }

        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.wav"
            audio_path.write_bytes(b"audio")
            output_dir = Path(directory) / "outputs"

            with (
                patch("app.services.stt_service.settings.output_dir", output_dir),
                patch("app.services.stt_service.settings.save_transcriptions", True),
            ):
                service = STTService()
                service._ffmpeg_available = False
                service.register_backend("local-stt-router", Backend())
                result = service.transcribe_file(str(audio_path))
                service.save_transcription(result)

            files = list((output_dir / "transcriptions").glob("*.json"))
            self.assertEqual(result["text"], "saved transcript")
            self.assertEqual(len(files), 1)
            saved = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(saved["model"], "local-stt")
            self.assertEqual(saved["text"], "saved transcript")


if __name__ == "__main__":
    unittest.main()
