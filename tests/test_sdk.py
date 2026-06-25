import sys
import unittest
from pathlib import Path


SDK_PATH = Path(__file__).resolve().parents[1] / "sdk" / "python"
sys.path.insert(0, str(SDK_PATH))

from local_tts_gateway.client import _multipart_file, _websocket_url


class PythonSDKTests(unittest.TestCase):
    def test_builds_conversation_websocket_url(self):
        self.assertEqual(
            _websocket_url("https://gateway.example", "/ws/conversation"),
            "wss://gateway.example/ws/conversation",
        )

    def test_builds_multipart_audio_request(self):
        audio_path = Path(__file__)
        body, boundary = _multipart_file(
            "file",
            audio_path,
            {"model": "local-stt"},
        )

        self.assertIn(boundary.encode(), body)
        self.assertIn(b'name="model"', body)
        self.assertIn(b'name="file"', body)
