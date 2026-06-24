import os
import unittest
import wave
from unittest.mock import patch

from app.services.realtime_stt import RealtimeSTTSession
from app.services.realtime_tts import take_ready_text


class RealtimeTTSBufferTests(unittest.TestCase):
    def test_extracts_complete_sentences_and_retains_partial_text(self):
        chunks, remainder = take_ready_text(
            "First sentence. Second sentence! Incomplete",
        )

        self.assertEqual(chunks, ["First sentence.", "Second sentence!"])
        self.assertEqual(remainder, "Incomplete")

    def test_force_flushes_incomplete_text(self):
        chunks, remainder = take_ready_text("Incomplete streamed text", force=True)

        self.assertEqual(chunks, ["Incomplete streamed text"])
        self.assertEqual(remainder, "")

    def test_long_text_is_split_at_configured_threshold(self):
        with patch("app.services.realtime_tts.settings.websocket_tts_flush_chars", 12):
            chunks, remainder = take_ready_text("one two three four five")

        self.assertEqual(chunks, ["one two", "three four"])
        self.assertEqual(remainder, "five")


class RealtimeSTTSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_snapshot_is_a_valid_wav(self):
        events = []

        async def send_event(event):
            events.append(event)

        session = RealtimeSTTSession(
            service=object(),
            send_event=send_event,
            request_id="snapshot-1",
            audio_format="pcm_s16le",
            sample_rate=16000,
            channels=1,
            partial_interval_ms=60000,
            min_audio_ms=1,
        )

        snapshot_path = None
        try:
            await session.append(b"\x00\x00" * 160)
            snapshot_path = session._create_snapshot()

            with wave.open(snapshot_path, "rb") as snapshot:
                self.assertEqual(snapshot.getnchannels(), 1)
                self.assertEqual(snapshot.getsampwidth(), 2)
                self.assertEqual(snapshot.getframerate(), 16000)
                self.assertEqual(snapshot.getnframes(), 160)
        finally:
            if snapshot_path and os.path.exists(snapshot_path):
                os.remove(snapshot_path)
            await session.close()


if __name__ == "__main__":
    unittest.main()
