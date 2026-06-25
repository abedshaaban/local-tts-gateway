import asyncio
import re
from collections.abc import Awaitable, Callable

from app.config import settings
from app.services.tts_service import TTSService


SendEvent = Callable[[dict], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]

SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?:[\"')\]]*)\s+|\n+")


class TextBackpressureError(ValueError):
    pass


def take_ready_text(buffer: str, force: bool = False) -> tuple[list[str], str]:
    chunks = []
    start = 0
    for match in SENTENCE_END_RE.finditer(buffer):
        end = match.end()
        text = buffer[start:end].strip()
        if text:
            chunks.append(text)
        start = end

    remainder = buffer[start:]
    while len(remainder) >= settings.websocket_tts_flush_chars:
        split_at = remainder.rfind(" ", 0, settings.websocket_tts_flush_chars + 1)
        if split_at <= 0:
            split_at = settings.websocket_tts_flush_chars
        text = remainder[:split_at].strip()
        if text:
            chunks.append(text)
        remainder = remainder[split_at:].lstrip()

    if force and remainder.strip():
        chunks.append(remainder.strip())
        remainder = ""

    return chunks, remainder


class RealtimeTTSSession:
    def __init__(
        self,
        service: TTSService,
        send_event: SendEvent,
        send_audio: SendAudio,
        request_id,
        voice: str,
        speed: float,
        lang_code: str,
        split_pattern: str,
    ):
        self.service = service
        self.send_event = send_event
        self.send_audio = send_audio
        self.request_id = request_id
        self.voice = voice
        self.speed = speed
        self.lang_code = lang_code
        self.split_pattern = split_pattern
        self.buffer = ""
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(
            maxsize=settings.websocket_tts_queue_max_segments
        )
        self.cancelled = False
        self.ending = False
        self.chunk_count = 0
        self.byte_count = 0
        self.text_segments = 0
        self._worker = asyncio.create_task(self._run())

    async def append_text(self, delta: str):
        if self.ending:
            raise ValueError("The TTS stream is already ending.")
        self._ensure_worker_running()
        if not delta:
            return
        if len(self.buffer) + len(delta) > settings.websocket_tts_max_buffer_chars:
            raise ValueError("TTS text buffer exceeds the configured limit.")
        self.buffer += delta
        await self._enqueue_ready(force=False)

    async def flush(self):
        self._ensure_worker_running()
        await self._enqueue_ready(force=True)

    async def finish(self):
        if self.ending:
            return
        self.ending = True
        if self._worker.done():
            await self._worker
            return
        await self._enqueue_ready(force=True)
        await self._put(None)
        await self._worker

    async def cancel(self, notify: bool = True):
        if self.cancelled:
            return
        self.cancelled = True
        self.ending = True
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
        if notify:
            await self.send_event(
                {
                    "type": "cancelled",
                    "request_id": self.request_id,
                    "chunks": self.chunk_count,
                    "bytes": self.byte_count,
                }
            )

    async def _enqueue_ready(self, force: bool):
        chunks, self.buffer = take_ready_text(self.buffer, force=force)
        for text in chunks:
            await self._put(text)

    def _ensure_worker_running(self):
        if self._worker.done():
            raise ValueError("The TTS synthesis worker is no longer running.")

    async def _put(self, item: str | None):
        self._ensure_worker_running()
        put_task = asyncio.create_task(self.queue.put(item))
        try:
            done, _pending = await asyncio.wait_for(
                asyncio.wait(
                    {put_task, self._worker},
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=settings.websocket_tts_backpressure_timeout_ms / 1000,
            )
        except asyncio.TimeoutError as error:
            put_task.cancel()
            await asyncio.gather(put_task, return_exceptions=True)
            raise TextBackpressureError(
                "TTS consumer did not accept text before the backpressure timeout."
            ) from error
        if put_task in done:
            return
        put_task.cancel()
        await asyncio.gather(put_task, return_exceptions=True)
        raise ValueError("The TTS synthesis worker stopped before accepting text.")

    async def _run(self):
        try:
            while True:
                text = await self.queue.get()
                if text is None:
                    break

                segment_index = self.text_segments
                self.text_segments += 1
                await self.send_event(
                    {
                        "type": "segment_start",
                        "request_id": self.request_id,
                        "segment": segment_index,
                        "text": text,
                    }
                )
                generator = self.service.stream_pcm(
                    text=text,
                    voice=self.voice,
                    speed=self.speed,
                    lang_code=self.lang_code,
                    split_pattern=self.split_pattern,
                )
                while not self.cancelled:
                    has_chunk, chunk = await asyncio.to_thread(
                        _next_audio_chunk,
                        generator,
                    )
                    if not has_chunk:
                        break
                    await self.send_audio(chunk)
                    self.chunk_count += 1
                    self.byte_count += len(chunk)

                await self.send_event(
                    {
                        "type": "segment_complete",
                        "request_id": self.request_id,
                        "segment": segment_index,
                    }
                )

            if not self.cancelled:
                await self.send_event(
                    {
                        "type": "complete",
                        "request_id": self.request_id,
                        "segments": self.text_segments,
                        "chunks": self.chunk_count,
                        "bytes": self.byte_count,
                    }
                )
        except asyncio.CancelledError:
            pass
        except Exception as error:
            await self.send_event(
                {
                    "type": "error",
                    "code": "synthesis_failed",
                    "message": f"Failed to generate speech: {error}",
                    "request_id": self.request_id,
                }
            )


def _next_audio_chunk(generator):
    try:
        return True, next(generator)
    except StopIteration:
        return False, None
