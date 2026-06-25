import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app.main import app


class OpenAICompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_lists_local_models(self):
        response = self.client.get("/v1/models")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["object"], "list")
        self.assertEqual(
            {model["id"] for model in response.json()["data"]},
            {"local-tts", "local-stt"},
        )

    def test_speech_pcm_is_openai_compatible_s16le(self):
        float_audio = np.array([-1.0, 0.0, 1.0], dtype=np.float32).tobytes()

        with patch(
            "app.main.tts_service.stream_pcm",
            return_value=iter([float_audio]),
        ):
            response = self.client.post(
                "/v1/audio/speech",
                json={
                    "model": "tts-1",
                    "input": "Hello",
                    "voice": "alloy",
                    "response_format": "pcm",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-audio-format"], "pcm_s16le")
        samples = np.frombuffer(response.content, dtype="<i2")
        self.assertEqual(samples.tolist(), [-32767, 0, 32767])

    def test_transcription_json_matches_openai_shape(self):
        result = {
            "text": "hello world",
            "language": "en",
            "engine_used": "test",
            "duration_seconds": 0.1,
        }
        with patch("app.main.stt_service.transcribe_file", return_value=result):
            response = self.client.post(
                "/v1/audio/transcriptions",
                data={"model": "whisper-1", "response_format": "json"},
                files={"file": ("speech.wav", b"audio", "audio/wav")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "hello world"})

    def test_speech_wav_returns_generated_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as audio:
            audio.write(b"RIFFtest")
            path = audio.name

        try:
            with patch(
                "app.main.tts_service.generate_wav",
                return_value=path,
            ):
                response = self.client.post(
                    "/v1/audio/speech",
                    json={
                        "model": "local-tts",
                        "input": "Hello",
                        "voice": "af_heart",
                        "response_format": "wav",
                    },
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"RIFFtest")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_speech_wav_is_retained_when_enabled(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as audio:
            audio.write(b"RIFFsaved")
            path = audio.name

        try:
            with (
                patch(
                    "app.main.tts_service.generate_wav",
                    return_value=path,
                ),
                patch("app.openai_compat.settings.save_generated_audio", True),
            ):
                response = self.client.post(
                    "/v1/audio/speech",
                    json={
                        "model": "local-tts",
                        "input": "Hello",
                        "voice": "af_heart",
                        "response_format": "wav",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
