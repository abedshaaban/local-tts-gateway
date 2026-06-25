import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class ConversationWebSocketTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_unified_socket_transcribes_and_speaks(self):
        transcript = {
            "text": "hello",
            "language": "en",
            "engine_used": "test",
            "duration_seconds": 0.01,
        }
        with (
            patch("app.main.stt_service.transcribe_file", return_value=transcript),
            patch(
                "app.main.tts_service.stream_pcm",
                return_value=iter([b"spoken"]),
            ),
        ):
            with self.client.websocket_connect("/ws/conversation") as websocket:
                websocket.send_json({"type": "session.start"})
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "session.ready",
                )

                websocket.send_bytes(b"\x00\x00" * 160)
                websocket.send_json({"type": "input_audio_buffer.commit"})
                partial = websocket.receive_json()
                self.assertEqual(
                    partial["type"],
                    "conversation.transcript.partial",
                )

                websocket.send_json(
                    {"type": "response.create", "text": "Hello back."}
                )
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "response.created",
                )
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "response.audio.segment_start",
                )
                self.assertEqual(websocket.receive_bytes(), b"spoken")
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "response.audio.segment_complete",
                )
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "response.audio.done",
                )

    def test_barge_in_interrupts_active_response(self):
        def slow_audio():
            yield b"first"
            time.sleep(0.2)
            yield b"second"

        with patch(
            "app.main.tts_service.stream_pcm",
            side_effect=lambda **_kwargs: slow_audio(),
        ):
            with self.client.websocket_connect("/ws/conversation") as websocket:
                websocket.send_json(
                    {
                        "type": "session.start",
                        "config": {
                            "vad_threshold": 0.01,
                            "barge_in": True,
                        },
                    }
                )
                websocket.receive_json()
                websocket.send_json(
                    {
                        "type": "response.create",
                        "response_id": "response-1",
                        "text": "Long response.",
                    }
                )
                websocket.receive_json()
                websocket.receive_json()
                websocket.receive_bytes()

                websocket.send_bytes(b"\xff\x7f" * 1600)
                interrupted = websocket.receive_json()
                self.assertEqual(interrupted["type"], "response.interrupted")
                self.assertEqual(interrupted["response_id"], "response-1")
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "input_audio_buffer.speech_started",
                )


if __name__ == "__main__":
    unittest.main()
