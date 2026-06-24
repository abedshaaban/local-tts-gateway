import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class WebSocketTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_tts_streams_pcm_frames_and_completion_metadata(self):
        chunks = [b"\x00\x01", b"\x02\x03\x04"]

        with patch("app.main.tts_service.stream_pcm", return_value=iter(chunks)):
            with self.client.websocket_connect("/ws/tts") as websocket:
                websocket.send_json(
                    {
                        "type": "synthesize",
                        "request_id": "tts-1",
                        "text": "Hello",
                    }
                )

                self.assertEqual(
                    websocket.receive_json(),
                    {
                        "type": "start",
                        "request_id": "tts-1",
                        "format": "float32le",
                        "sample_rate": 24000,
                        "channels": 1,
                    },
                )
                self.assertEqual(websocket.receive_bytes(), chunks[0])
                self.assertEqual(websocket.receive_bytes(), chunks[1])
                self.assertEqual(
                    websocket.receive_json(),
                    {
                        "type": "complete",
                        "request_id": "tts-1",
                        "chunks": 2,
                        "bytes": 5,
                    },
                )

    def test_tts_returns_validation_errors_without_closing_connection(self):
        with self.client.websocket_connect("/ws/tts") as websocket:
            websocket.send_json({"type": "synthesize", "text": ""})
            error = websocket.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], "invalid_request")

            with patch("app.main.tts_service.stream_pcm", return_value=iter([b"ok"])):
                websocket.send_json({"text": "Valid request"})
                self.assertEqual(websocket.receive_json()["type"], "start")
                self.assertEqual(websocket.receive_bytes(), b"ok")
                self.assertEqual(websocket.receive_json()["type"], "complete")

    def test_stt_accepts_binary_frames_and_returns_transcription(self):
        captured = {}

        def transcribe(path):
            with open(path, "rb") as audio_file:
                captured["audio"] = audio_file.read()
            captured["suffix"] = os.path.splitext(path)[1]
            return {
                "text": "hello world",
                "language": "en",
                "engine_used": "test",
                "duration_seconds": 0.01,
            }

        with patch("app.main.stt_service.transcribe_file", side_effect=transcribe):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-1",
                        "format": "webm",
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "ready")
                self.assertEqual(ready["request_id"], "stt-1")

                websocket.send_bytes(b"audio-")
                websocket.send_bytes(b"bytes")
                websocket.send_json({"type": "end"})

                result = websocket.receive_json()
                self.assertEqual(
                    result,
                    {
                        "type": "transcription",
                        "request_id": "stt-1",
                        "text": "hello world",
                        "language": "en",
                        "engine_used": "test",
                        "duration_seconds": 0.01,
                    },
                )

        self.assertEqual(captured["audio"], b"audio-bytes")
        self.assertEqual(captured["suffix"], ".webm")

    def test_stt_rejects_binary_data_before_start(self):
        with self.client.websocket_connect("/ws/stt") as websocket:
            websocket.send_bytes(b"audio")
            error = websocket.receive_json()
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], "upload_not_started")


if __name__ == "__main__":
    unittest.main()
