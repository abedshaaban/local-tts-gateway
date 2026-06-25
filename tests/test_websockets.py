import math
import os
import struct
import unittest
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class WebSocketTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    @staticmethod
    def generated_pcm_speech(
        sample_rate: int = 16000,
        duration_seconds: float = 0.3,
    ) -> bytes:
        samples = []
        for index in range(int(sample_rate * duration_seconds)):
            t = index / sample_rate
            envelope = 0.25 + 0.75 * abs(math.sin(2 * math.pi * 4 * t))
            value = int(12000 * envelope * math.sin(2 * math.pi * 180 * t))
            samples.append(value)
        return struct.pack(f"<{len(samples)}h", *samples)

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

    def test_stt_idle_timeout_returns_request_id_and_closes_session(self):
        with patch.object(settings, "websocket_idle_timeout_seconds", 0.01):
            with self.client.websocket_connect("/ws/stt") as websocket:
                error = websocket.receive_json()
                self.assertEqual(error["type"], "error")
                self.assertEqual(error["code"], "session_timeout")
                self.assertTrue(error["request_id"].startswith("ws_"))

    def test_tts_accepts_incremental_text_and_streams_audio(self):
        generated_text = []

        def stream_pcm(**kwargs):
            generated_text.append(kwargs["text"])
            return iter([kwargs["text"].encode()])

        with patch("app.main.tts_service.stream_pcm", side_effect=stream_pcm):
            with self.client.websocket_connect("/ws/tts") as websocket:
                websocket.send_json(
                    {
                        "type": "stream_start",
                        "request_id": "tts-live",
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "ready")
                self.assertEqual(ready["request_id"], "tts-live")

                websocket.send_json({"type": "text_delta", "text": "Hello "})
                websocket.send_json(
                    {"type": "text_delta", "text": "from a streamed model. "}
                )

                segment_start = websocket.receive_json()
                self.assertEqual(segment_start["type"], "segment_start")
                self.assertEqual(
                    segment_start["text"],
                    "Hello from a streamed model.",
                )
                self.assertEqual(
                    websocket.receive_bytes(),
                    b"Hello from a streamed model.",
                )
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "segment_complete",
                )

                websocket.send_json({"type": "text_delta", "text": "Last words"})
                websocket.send_json({"type": "end"})
                self.assertEqual(websocket.receive_json()["type"], "segment_start")
                self.assertEqual(websocket.receive_bytes(), b"Last words")
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "segment_complete",
                )
                complete = websocket.receive_json()
                self.assertEqual(complete["type"], "complete")
                self.assertEqual(complete["segments"], 2)

        self.assertEqual(
            generated_text,
            ["Hello from a streamed model.", "Last words"],
        )

    def test_realtime_stt_emits_partial_and_final_transcripts(self):
        calls = []

        def transcribe(path):
            calls.append(path)
            return {
                "text": f"version {len(calls)}",
                "language": "en",
                "engine_used": "test",
                "duration_seconds": 0.01,
            }

        with patch("app.main.stt_service.transcribe_file", side_effect=transcribe):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-live",
                        "format": "pcm_s16le",
                        "sample_rate": 16000,
                        "channels": 1,
                        "realtime": True,
                        "partial_interval_ms": 60000,
                        "min_audio_ms": 1,
                        "vad_threshold": 1,
                    }
                )
                ready = websocket.receive_json()
                self.assertTrue(ready["realtime"])

                websocket.send_bytes(b"\x00\x00" * 160)
                websocket.send_json({"type": "commit"})
                partial = websocket.receive_json()
                self.assertEqual(partial["type"], "partial_transcript")
                self.assertEqual(partial["text"], "version 1")

                websocket.send_json({"type": "end"})
                final = websocket.receive_json()
                self.assertEqual(final["type"], "final_transcript")
                self.assertEqual(final["text"], "version 2")

        self.assertEqual(len(calls), 2)

    def test_realtime_stt_integrates_generated_pcm_speech(self):
        observed = {}

        def transcribe(path):
            with wave.open(path, "rb") as audio:
                pcm = audio.readframes(audio.getnframes())
                observed["frames"] = audio.getnframes()
                observed["sample_rate"] = audio.getframerate()
            samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
            observed["peak"] = max(abs(sample) for sample in samples)
            return {
                "text": "generated speech",
                "language": "en",
                "engine_used": "generated-pcm-test",
                "duration_seconds": 0.01,
            }

        pcm = self.generated_pcm_speech()
        with patch("app.main.stt_service.transcribe_file", side_effect=transcribe):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-generated-pcm",
                        "format": "pcm_s16le",
                        "sample_rate": 16000,
                        "channels": 1,
                        "realtime": True,
                        "partial_interval_ms": 60000,
                        "min_audio_ms": 1,
                        "vad_threshold": 1,
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["queue_max_chunks"], 64)

                for offset in range(0, len(pcm), 640):
                    websocket.send_bytes(pcm[offset : offset + 640])
                websocket.send_json({"type": "end"})

                final = websocket.receive_json()
                self.assertEqual(final["type"], "final_transcript")
                self.assertEqual(final["text"], "generated speech")

        self.assertEqual(observed["sample_rate"], 16000)
        self.assertEqual(observed["frames"], len(pcm) // 2)
        self.assertGreater(observed["peak"], 1000)

    def test_realtime_stt_emits_voice_activity_events(self):
        result = {
            "text": "spoken words",
            "language": "en",
            "engine_used": "test",
            "duration_seconds": 0.01,
        }

        with patch("app.main.stt_service.transcribe_file", return_value=result):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-vad",
                        "format": "pcm_s16le",
                        "sample_rate": 16000,
                        "realtime": True,
                        "partial_interval_ms": 60000,
                        "min_audio_ms": 1,
                        "vad_threshold": 0.01,
                        "vad_silence_ms": 50,
                    }
                )
                websocket.receive_json()

                websocket.send_bytes(b"\xff\x7f" * 1600)
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "speech_started",
                )

                websocket.send_bytes(b"\x00\x00" * 1600)
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "speech_stopped",
                )
                self.assertEqual(
                    websocket.receive_json()["type"],
                    "final_transcript",
                )

                websocket.send_json({"type": "abort"})
                self.assertEqual(websocket.receive_json()["type"], "aborted")

    def test_realtime_stt_automatically_emits_partials(self):
        result = {
            "text": "automatic partial",
            "language": "en",
            "engine_used": "test",
            "duration_seconds": 0.01,
        }

        with patch("app.main.stt_service.transcribe_file", return_value=result):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-auto",
                        "format": "pcm_s16le",
                        "sample_rate": 16000,
                        "realtime": True,
                        "partial_interval_ms": 100,
                        "min_audio_ms": 1,
                        "vad_threshold": 1,
                    }
                )
                websocket.receive_json()
                websocket.send_bytes(b"\x00\x00" * 160)

                partial = websocket.receive_json()
                self.assertEqual(partial["type"], "partial_transcript")
                self.assertEqual(partial["text"], "automatic partial")

                websocket.send_json({"type": "abort"})
                self.assertEqual(websocket.receive_json()["type"], "aborted")

    def test_realtime_stt_reports_engine_failures_without_closing_socket(self):
        with patch(
            "app.main.stt_service.transcribe_file",
            side_effect=RuntimeError("model failed"),
        ):
            with self.client.websocket_connect("/ws/stt") as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "request_id": "stt-error",
                        "format": "pcm_s16le",
                        "realtime": True,
                        "partial_interval_ms": 60000,
                        "min_audio_ms": 1,
                        "vad_threshold": 1,
                    }
                )
                websocket.receive_json()
                websocket.send_bytes(b"\x00\x00" * 160)
                websocket.send_json({"type": "end"})

                error = websocket.receive_json()
                self.assertEqual(error["type"], "error")
                self.assertEqual(error["code"], "transcription_failed")

    def test_incremental_tts_recovers_after_synthesis_failure(self):
        with patch(
            "app.main.tts_service.stream_pcm",
            side_effect=RuntimeError("model failed"),
        ):
            with self.client.websocket_connect("/ws/tts") as websocket:
                websocket.send_json(
                    {
                        "type": "stream_start",
                        "request_id": "tts-error",
                    }
                )
                websocket.receive_json()
                websocket.send_json(
                    {"type": "text_delta", "text": "This will fail. "}
                )

                self.assertEqual(websocket.receive_json()["type"], "segment_start")
                error = websocket.receive_json()
                self.assertEqual(error["type"], "error")
                self.assertEqual(error["code"], "synthesis_failed")

                websocket.send_json({"type": "end"})
                websocket.send_json(
                    {
                        "type": "stream_start",
                        "request_id": "tts-next",
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "ready")
                self.assertEqual(ready["request_id"], "tts-next")


if __name__ == "__main__":
    unittest.main()
