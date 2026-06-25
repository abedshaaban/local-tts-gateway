import asyncio
import json
import mimetypes
import uuid
from pathlib import Path
from urllib import request
from urllib.parse import urljoin, urlparse, urlunparse


def _websocket_url(base_url: str, path: str) -> str:
    parsed = urlparse(urljoin(base_url, path))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=scheme))


def _multipart_file(
    field_name: str,
    path: Path,
    fields: dict[str, str],
) -> tuple[bytes, str]:
    boundary = f"----local-tts-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode(),
            f"Content-Type: {media_type}\r\n\r\n".encode(),
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), boundary


class LocalTTSGateway:
    def __init__(self, base_url: str = "http://127.0.0.1:47829"):
        self.base_url = base_url.rstrip("/") + "/"

    def speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        response_format: str = "wav",
        speed: float = 1,
    ) -> bytes:
        payload = json.dumps(
            {
                "model": "local-tts",
                "input": text,
                "voice": voice,
                "response_format": response_format,
                "speed": speed,
            }
        ).encode()
        req = request.Request(
            urljoin(self.base_url, "v1/audio/speech"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req) as response:
            return response.read()

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        response_format: str = "json",
    ):
        path = Path(audio_path)
        body, boundary = _multipart_file(
            "file",
            path,
            {
                "model": "local-stt",
                "response_format": response_format,
            },
        )
        req = request.Request(
            urljoin(self.base_url, "v1/audio/transcriptions"),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with request.urlopen(req) as response:
            content = response.read().decode()
            return content if response_format == "text" else json.loads(content)

    def conversation(self, **kwargs):
        return ConversationClient(self.base_url, **kwargs)


class ConversationClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:47829",
        *,
        barge_in: bool = True,
        reconnect_attempts: int = 3,
        reconnect_delay: float = 0.75,
    ):
        self.url = _websocket_url(base_url, "/ws/conversation")
        self.barge_in = barge_in
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.websocket = None
        self._closed = False

    async def connect(self):
        import websockets

        self._closed = False
        last_error = None
        for attempt in range(self.reconnect_attempts + 1):
            try:
                self.websocket = await websockets.connect(
                    self.url,
                    max_size=None,
                )
                await self.send_event(
                    {
                        "type": "session.start",
                        "config": {
                            "format": "pcm_s16le",
                            "sample_rate": 16000,
                            "channels": 1,
                            "barge_in": self.barge_in,
                        },
                    }
                )
                return await self.receive()
            except Exception as error:
                last_error = error
                if attempt < self.reconnect_attempts:
                    await asyncio.sleep(self.reconnect_delay)
        raise RuntimeError(f"Failed to connect: {last_error}")

    async def send_event(self, event: dict):
        if self.websocket is None:
            raise RuntimeError("Conversation is not connected.")
        await self.websocket.send(json.dumps(event))

    async def send_audio(self, pcm_s16le: bytes):
        if self.websocket is None:
            raise RuntimeError("Conversation is not connected.")
        await self.websocket.send(pcm_s16le)

    async def create_response(self, text: str, response_id: str | None = None):
        await self.send_event(
            {
                "type": "response.create",
                "response_id": response_id,
                "text": text,
            }
        )

    async def append_response_text(self, text: str):
        await self.send_event({"type": "response.text.delta", "text": text})

    async def receive(self):
        if self.websocket is None:
            raise RuntimeError("Conversation is not connected.")
        message = await self.websocket.recv()
        if isinstance(message, bytes):
            return {"type": "audio", "data": message}
        return json.loads(message)

    async def events(self):
        import websockets

        while not self._closed:
            try:
                yield await self.receive()
            except websockets.ConnectionClosed:
                if self._closed:
                    break
                await self.connect()

    async def close(self):
        self._closed = True
        if self.websocket is not None:
            await self.send_event({"type": "session.end"})
            await self.websocket.close()
            self.websocket = None
