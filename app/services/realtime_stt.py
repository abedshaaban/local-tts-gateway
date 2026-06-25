import asyncio
import os
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

from app.config import settings
from app.services.stt_service import STTService


SendEvent = Callable[[dict], Awaitable[None]]

PCM_FORMATS = {"pcm_s16le", "s16le"}
UPLOAD_FORMATS = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "webm"}


def common_word_prefix(left: str, right: str) -> str:
    left_words = left.split()
    right_words = right.split()
    count = 0
    for left_word, right_word in zip(left_words, right_words):
        if left_word != right_word:
            break
        count += 1
    return " ".join(right_words[:count])


class TranscriptStabilizer:
    def __init__(self):
        self.previous = ""
        self.stable = ""

    def update(self, text: str) -> tuple[str, str]:
        shared = common_word_prefix(self.previous, text)
        self.stable = shared
        self.previous = text

        stable_words = len(self.stable.split())
        unstable = " ".join(text.split()[stable_words:])
        return self.stable, unstable

    def finalize(self, text: str) -> tuple[str, str]:
        self.previous = text
        self.stable = text
        return text, ""

    def reset(self):
        self.previous = ""
        self.stable = ""


class RealtimeSTTSession:
    def __init__(
        self,
        service: STTService,
        send_event: SendEvent,
        request_id,
        audio_format: str,
        sample_rate: int = 16000,
        channels: int = 1,
        partial_interval_ms: int | None = None,
        min_audio_ms: int | None = None,
        vad_threshold: float | None = None,
        vad_silence_ms: int | None = None,
        rolling_window_ms: int | None = None,
    ):
        self.service = service
        self.send_event = send_event
        self.request_id = request_id
        self.audio_format = audio_format
        self.sample_rate = sample_rate
        self.channels = channels
        self.partial_interval_ms = (
            partial_interval_ms
            if partial_interval_ms is not None
            else settings.websocket_stt_partial_interval_ms
        )
        self.min_audio_ms = (
            min_audio_ms
            if min_audio_ms is not None
            else settings.websocket_stt_min_audio_ms
        )
        self.vad_threshold = (
            vad_threshold
            if vad_threshold is not None
            else settings.websocket_stt_vad_threshold
        )
        self.vad_silence_ms = (
            vad_silence_ms
            if vad_silence_ms is not None
            else settings.websocket_stt_vad_silence_ms
        )
        self.rolling_window_ms = (
            rolling_window_ms
            if rolling_window_ms is not None
            else settings.websocket_stt_rolling_window_ms
        )

        suffix = ".pcm" if audio_format in PCM_FORMATS else f".{audio_format}"
        self._file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        self.path = self._file.name
        self.byte_count = 0
        self._last_transcribed_bytes = 0
        self._latest_text = ""
        self._revision = 0
        self._closed = False
        self._transcription_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._partial_task: asyncio.Task | None = None
        self._speech_active = False
        self._silence_ms = 0.0
        self._utterance_start_byte = 0
        self._last_append_start_byte = 0
        self._snapshot_start_ms = 0.0
        self._snapshot_end_ms = 0.0
        self._stabilizer = TranscriptStabilizer()

    @property
    def bytes_per_ms(self) -> float | None:
        if self.audio_format not in PCM_FORMATS:
            return None
        return self.sample_rate * self.channels * 2 / 1000

    @property
    def audio_duration_ms(self) -> float | None:
        if not self.bytes_per_ms:
            return None
        return self.byte_count / self.bytes_per_ms

    def start(self):
        self._partial_task = asyncio.create_task(self._partial_loop())

    async def append(self, data: bytes):
        if self._closed:
            raise RuntimeError("The audio session is closed.")
        if self.byte_count + len(data) > settings.websocket_stt_max_bytes:
            raise ValueError("Audio upload exceeds the configured size limit.")

        self._last_append_start_byte = self.byte_count
        self._file.write(data)
        self._file.flush()
        self.byte_count += len(data)

        if self.audio_format in PCM_FORMATS:
            await self._update_vad(data)

    async def _update_vad(self, data: bytes):
        frame_size = 2 * self.channels
        usable = len(data) - (len(data) % frame_size)
        if usable <= 0:
            return

        samples = np.frombuffer(data[:usable], dtype="<i2")
        if self.channels > 1:
            samples = samples.reshape(-1, self.channels).mean(axis=1)
        rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32) / 32768.0))))
        duration_ms = len(data) / (self.sample_rate * self.channels * 2) * 1000

        if rms >= self.vad_threshold:
            self._silence_ms = 0.0
            if not self._speech_active:
                self._speech_active = True
                self._utterance_start_byte = self._last_append_start_byte
                self._stabilizer.reset()
                await self.send_event(
                    {
                        "type": "speech_started",
                        "request_id": self.request_id,
                    }
                )
            return

        if not self._speech_active:
            return

        self._silence_ms += duration_ms
        if self._silence_ms >= self.vad_silence_ms:
            self._speech_active = False
            self._silence_ms = 0.0
            await self.send_event(
                {
                    "type": "speech_stopped",
                    "request_id": self.request_id,
                }
            )
            await self.transcribe(event_type="final_transcript", force=True)

    def _has_minimum_audio(self) -> bool:
        duration_ms = self.audio_duration_ms
        if duration_ms is None:
            return self.byte_count > 0
        return duration_ms >= self.min_audio_ms

    async def _partial_loop(self):
        interval = max(self.partial_interval_ms, 100) / 1000
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

                if self._stop.is_set():
                    break
                try:
                    await self.transcribe(event_type="partial_transcript")
                except Exception:
                    # Compressed streams can be temporarily undecodable between
                    # container boundaries. A later snapshot or the final file
                    # can still transcribe successfully.
                    continue
        except asyncio.CancelledError:
            pass

    def _create_snapshot(self) -> str:
        self._file.flush()
        if self.audio_format in PCM_FORMATS:
            snapshot = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            snapshot.close()
            frame_size = self.channels * 2
            rolling_bytes = int(
                self.sample_rate
                * frame_size
                * (self.rolling_window_ms / 1000)
            )
            start_byte = max(
                self._utterance_start_byte,
                self.byte_count - rolling_bytes,
            )
            start_byte -= start_byte % frame_size
            with open(self.path, "rb") as source:
                source.seek(start_byte)
                pcm = source.read()
            with wave.open(snapshot.name, "wb") as output:
                output.setnchannels(self.channels)
                output.setsampwidth(2)
                output.setframerate(self.sample_rate)
                output.writeframes(pcm)
            bytes_per_ms = self.bytes_per_ms or 1
            self._snapshot_start_ms = start_byte / bytes_per_ms
            self._snapshot_end_ms = self.byte_count / bytes_per_ms
            return snapshot.name

        self._snapshot_start_ms = 0.0
        self._snapshot_end_ms = 0.0
        snapshot = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=Path(self.path).suffix,
        )
        snapshot.close()
        shutil.copyfile(self.path, snapshot.name)
        return snapshot.name

    async def transcribe(self, event_type: str, force: bool = False):
        if self.byte_count == 0:
            return None
        if not force and not self._has_minimum_audio():
            return None
        if not force and self.byte_count == self._last_transcribed_bytes:
            return None
        if self._transcription_lock.locked() and not force:
            return None

        async with self._transcription_lock:
            snapshot_path = await asyncio.to_thread(self._create_snapshot)
            snapshot_bytes = self.byte_count
            try:
                transcription = asyncio.create_task(
                    asyncio.to_thread(
                        self.service.transcribe_file,
                        snapshot_path,
                    )
                )
                try:
                    result = await asyncio.shield(transcription)
                except asyncio.CancelledError:
                    await transcription
                    raise
            finally:
                if os.path.exists(snapshot_path):
                    os.remove(snapshot_path)

            self._last_transcribed_bytes = snapshot_bytes
            text = result.get("text", "")
            if event_type == "partial_transcript" and text == self._latest_text:
                return result
            self._latest_text = text
            if event_type == "partial_transcript":
                stable_text, unstable_text = self._stabilizer.update(text)
            else:
                stable_text, unstable_text = self._stabilizer.finalize(text)
                self.service.save_transcription(result)
            self._revision += 1
            await self.send_event(
                {
                    "type": event_type,
                    "request_id": self.request_id,
                    "revision": self._revision,
                    "audio_bytes": snapshot_bytes,
                    "window_start_ms": round(self._snapshot_start_ms, 1),
                    "window_end_ms": round(self._snapshot_end_ms, 1),
                    "stable_text": stable_text,
                    "unstable_text": unstable_text,
                    **result,
                }
            )
            return result

    async def finish(self):
        await self._stop_worker()
        if self.byte_count == 0:
            raise ValueError("No audio data was received.")
        return await self.transcribe(event_type="final_transcript", force=True)

    async def _stop_worker(self):
        self._stop.set()
        if self._partial_task is not None:
            self._partial_task.cancel()
            await asyncio.gather(self._partial_task, return_exceptions=True)
            self._partial_task = None

    async def close(self):
        if self._closed:
            return
        self._closed = True
        await self._stop_worker()
        if not self._file.closed:
            self._file.close()
        if os.path.exists(self.path):
            os.remove(self.path)
