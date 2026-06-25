import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class ElevenLabsCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_lists_voices_using_elevenlabs_shape(self):
        response = self.client.get("/v1/voices")

        self.assertEqual(response.status_code, 200)
        self.assertIn("voices", response.json())
        self.assertIn("has_more", response.json())
        self.assertIn("total_count", response.json())
        self.assertIn("voice_id", response.json()["voices"][0])

    def test_gets_voice_by_openai_alias(self):
        response = self.client.get("/v1/voices/alloy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["voice_id"], "af_heart")

    def test_generates_speech_with_elevenlabs_model_alias(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as audio:
            audio.write(b"RIFFtest")
            path = audio.name

        try:
            with patch(
                "app.main.tts_service.generate_wav",
                return_value=path,
            ) as generate:
                response = self.client.post(
                    "/v1/text-to-speech/alloy?output_format=wav_24000",
                    json={
                        "text": "Hello",
                        "model_id": "eleven_multilingual_v2",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"RIFFtest")
            self.assertIn("request-id", response.headers)
            self.assertEqual(
                generate.call_args.kwargs["model"],
                "eleven_multilingual_v2",
            )
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_lists_models_under_namespaced_elevenlabs_route(self):
        response = self.client.get("/elevenlabs/v1/models")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["model_id"], "local-tts")
        self.assertTrue(response.json()[0]["can_do_text_to_speech"])


if __name__ == "__main__":
    unittest.main()
