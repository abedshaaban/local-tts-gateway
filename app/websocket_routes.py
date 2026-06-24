import asyncio
import json
import os
import tempfile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import settings
from app.schemas import TTSRequest
from app.services.stt_service import STTService
from app.services.tts_service import TTSService


def _next_audio_chunk(generator):
    try:
        return True, next(generator)
    except StopIteration:
        return False, None


def _error(message: str, request_id=None, code: str = "request_error"):
    response = {
        "type": "error",
        "code": code,
        "message": message,
    }
    if request_id is not None:
        response["request_id"] = request_id
    return response


def create_websocket_router(
    tts_service: TTSService,
    stt_service: STTService,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/tts")
    async def websocket_tts(websocket: WebSocket):
        await websocket.accept()

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                text = message.get("text")
                if text is None:
                    await websocket.send_json(
                        _error(
                            "TTS requests must be JSON text messages.",
                            code="invalid_message",
                        )
                    )
                    continue

                request_id = None
                try:
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("Request must be a JSON object.")

                    request_id = data.pop("request_id", None)
                    message_type = data.pop("type", "synthesize")
                    if message_type != "synthesize":
                        raise ValueError("TTS message type must be 'synthesize'.")

                    payload = TTSRequest.model_validate(data)
                except (json.JSONDecodeError, ValidationError, ValueError) as error:
                    await websocket.send_json(
                        _error(
                            str(error),
                            request_id=request_id,
                            code="invalid_request",
                        )
                    )
                    continue

                try:
                    await websocket.send_json(
                        {
                            "type": "start",
                            "request_id": request_id,
                            "format": "float32le",
                            "sample_rate": settings.sample_rate,
                            "channels": 1,
                        }
                    )

                    generator = tts_service.stream_pcm(
                        text=payload.text,
                        voice=payload.voice,
                        speed=payload.speed,
                        lang_code=payload.lang_code,
                        split_pattern=payload.split_pattern,
                    )
                    chunk_count = 0
                    byte_count = 0

                    while True:
                        has_chunk, chunk = await asyncio.to_thread(
                            _next_audio_chunk,
                            generator,
                        )
                        if not has_chunk:
                            break

                        await websocket.send_bytes(chunk)
                        chunk_count += 1
                        byte_count += len(chunk)

                    await websocket.send_json(
                        {
                            "type": "complete",
                            "request_id": request_id,
                            "chunks": chunk_count,
                            "bytes": byte_count,
                        }
                    )
                except WebSocketDisconnect:
                    break
                except Exception as error:
                    await websocket.send_json(
                        _error(
                            f"Failed to generate speech: {error}",
                            request_id=request_id,
                            code="synthesis_failed",
                        )
                    )
        except WebSocketDisconnect:
            pass

    @router.websocket("/ws/stt")
    async def websocket_stt(websocket: WebSocket):
        await websocket.accept()

        allowed_formats = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "webm"}
        temp_file = None
        temp_path = None
        request_id = None
        byte_count = 0

        def cleanup_upload():
            nonlocal temp_file, temp_path, request_id, byte_count
            if temp_file is not None and not temp_file.closed:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            temp_file = None
            temp_path = None
            request_id = None
            byte_count = 0

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                binary = message.get("bytes")
                if binary is not None:
                    if temp_file is None:
                        await websocket.send_json(
                            _error(
                                "Send a JSON 'start' message before audio data.",
                                code="upload_not_started",
                            )
                        )
                        continue

                    if byte_count + len(binary) > settings.websocket_stt_max_bytes:
                        current_request_id = request_id
                        cleanup_upload()
                        await websocket.send_json(
                            _error(
                                "Audio upload exceeds the configured size limit.",
                                request_id=current_request_id,
                                code="upload_too_large",
                            )
                        )
                        continue

                    temp_file.write(binary)
                    byte_count += len(binary)
                    continue

                text = message.get("text")
                if text is None:
                    continue

                try:
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("Control message must be a JSON object.")
                except (json.JSONDecodeError, ValueError) as error:
                    await websocket.send_json(
                        _error(str(error), code="invalid_message")
                    )
                    continue

                message_type = data.get("type")

                if message_type == "start":
                    cleanup_upload()
                    request_id = data.get("request_id")
                    audio_format = str(data.get("format", "webm")).lower().lstrip(".")
                    if audio_format not in allowed_formats:
                        await websocket.send_json(
                            _error(
                                f"Unsupported audio format: {audio_format}. "
                                f"Supported: {sorted(allowed_formats)}",
                                request_id=request_id,
                                code="unsupported_format",
                            )
                        )
                        request_id = None
                        continue

                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=f".{audio_format}",
                    )
                    temp_path = temp_file.name
                    await websocket.send_json(
                        {
                            "type": "ready",
                            "request_id": request_id,
                            "max_bytes": settings.websocket_stt_max_bytes,
                        }
                    )
                    continue

                if message_type == "abort":
                    aborted_request_id = request_id
                    cleanup_upload()
                    await websocket.send_json(
                        {
                            "type": "aborted",
                            "request_id": aborted_request_id,
                        }
                    )
                    continue

                if message_type == "end":
                    if temp_file is None or temp_path is None:
                        await websocket.send_json(
                            _error(
                                "No active audio upload.",
                                request_id=request_id,
                                code="upload_not_started",
                            )
                        )
                        continue

                    completed_request_id = request_id
                    completed_path = temp_path
                    completed_bytes = byte_count
                    temp_file.close()
                    temp_file = None

                    if completed_bytes == 0:
                        cleanup_upload()
                        await websocket.send_json(
                            _error(
                                "No audio data was received.",
                                request_id=completed_request_id,
                                code="empty_upload",
                            )
                        )
                        continue

                    try:
                        result = await asyncio.to_thread(
                            stt_service.transcribe_file,
                            completed_path,
                        )
                        await websocket.send_json(
                            {
                                "type": "transcription",
                                "request_id": completed_request_id,
                                **result,
                            }
                        )
                    except Exception as error:
                        await websocket.send_json(
                            _error(
                                f"Failed to transcribe audio: {error}",
                                request_id=completed_request_id,
                                code="transcription_failed",
                            )
                        )
                    finally:
                        cleanup_upload()
                    continue

                await websocket.send_json(
                    _error(
                        "STT control message type must be 'start', 'end', or 'abort'.",
                        request_id=request_id,
                        code="invalid_message_type",
                    )
                )
        except WebSocketDisconnect:
            pass
        finally:
            cleanup_upload()

    return router
