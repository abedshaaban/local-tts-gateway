import asyncio
import json
import os
import tempfile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import settings
from app.schemas import TTSRequest
from app.services.realtime_stt import PCM_FORMATS, UPLOAD_FORMATS, RealtimeSTTSession
from app.services.realtime_tts import RealtimeTTSSession
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
        send_lock = asyncio.Lock()
        session: RealtimeTTSSession | None = None

        async def send_json(payload: dict):
            async with send_lock:
                await websocket.send_json(payload)

        async def send_bytes(payload: bytes):
            async with send_lock:
                await websocket.send_bytes(payload)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                text = message.get("text")
                if text is None:
                    await send_json(
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

                    request_id = data.get("request_id")
                    message_type = data.get("type", "synthesize")
                except (json.JSONDecodeError, ValidationError, ValueError) as error:
                    await send_json(
                        _error(
                            str(error),
                            request_id=request_id,
                            code="invalid_request",
                        )
                    )
                    continue

                if message_type == "stream_start":
                    if session is not None:
                        await send_json(
                            _error(
                                "A TTS stream is already active.",
                                request_id=request_id,
                                code="stream_already_active",
                            )
                        )
                        continue
                    try:
                        validation_data = {
                            key: value
                            for key, value in data.items()
                            if key not in {"type", "request_id"}
                        }
                        payload = TTSRequest.model_validate(
                            {"text": "_", **validation_data}
                        )
                        session = RealtimeTTSSession(
                            service=tts_service,
                            send_event=send_json,
                            send_audio=send_bytes,
                            request_id=request_id,
                            voice=payload.voice,
                            speed=payload.speed,
                            lang_code=payload.lang_code,
                            split_pattern=payload.split_pattern,
                        )
                        await send_json(
                            {
                                "type": "ready",
                                "request_id": request_id,
                                "format": "float32le",
                                "sample_rate": settings.sample_rate,
                                "channels": 1,
                                "max_buffer_chars": settings.websocket_tts_max_buffer_chars,
                            }
                        )
                    except (ValidationError, ValueError) as error:
                        await send_json(
                            _error(
                                str(error),
                                request_id=request_id,
                                code="invalid_request",
                            )
                        )
                    continue

                if message_type in {"text_delta", "flush", "end", "cancel"}:
                    if session is None:
                        await send_json(
                            _error(
                                "Send 'stream_start' before streaming text.",
                                request_id=request_id,
                                code="stream_not_started",
                            )
                        )
                        continue
                    active_session = session
                    try:
                        if message_type == "text_delta":
                            delta = data.get("text", data.get("delta", ""))
                            if not isinstance(delta, str):
                                raise ValueError("'text' must be a string.")
                            await active_session.append_text(delta)
                        elif message_type == "flush":
                            await active_session.flush()
                        elif message_type == "end":
                            try:
                                await active_session.finish()
                            finally:
                                session = None
                        else:
                            await active_session.cancel()
                            session = None
                    except ValueError as error:
                        await send_json(
                            _error(
                                str(error),
                                request_id=active_session.request_id,
                                code="invalid_request",
                            )
                        )
                    continue

                if message_type != "synthesize":
                    await send_json(
                        _error(
                            "TTS message type must be 'synthesize', 'stream_start', "
                            "'text_delta', 'flush', 'end', or 'cancel'.",
                            request_id=request_id,
                            code="invalid_message_type",
                        )
                    )
                    continue

                try:
                    payload_data = {
                        key: value
                        for key, value in data.items()
                        if key not in {"type", "request_id"}
                    }
                    payload = TTSRequest.model_validate(payload_data)
                    await send_json(
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

                        await send_bytes(chunk)
                        chunk_count += 1
                        byte_count += len(chunk)

                    await send_json(
                        {
                            "type": "complete",
                            "request_id": request_id,
                            "chunks": chunk_count,
                            "bytes": byte_count,
                        }
                    )
                except ValidationError as error:
                    await send_json(
                        _error(
                            str(error),
                            request_id=request_id,
                            code="invalid_request",
                        )
                    )
                except WebSocketDisconnect:
                    break
                except Exception as error:
                    await send_json(
                        _error(
                            f"Failed to generate speech: {error}",
                            request_id=request_id,
                            code="synthesis_failed",
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if session is not None:
                await session.cancel(notify=False)

    @router.websocket("/ws/stt")
    async def websocket_stt(websocket: WebSocket):
        await websocket.accept()

        allowed_formats = UPLOAD_FORMATS
        temp_file = None
        temp_path = None
        request_id = None
        byte_count = 0
        realtime_session: RealtimeSTTSession | None = None
        send_lock = asyncio.Lock()

        async def send_json(payload: dict):
            async with send_lock:
                await websocket.send_json(payload)

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
                    if realtime_session is not None:
                        try:
                            await realtime_session.append(binary)
                        except ValueError as error:
                            failed_request_id = realtime_session.request_id
                            await realtime_session.close()
                            realtime_session = None
                            await send_json(
                                _error(
                                    str(error),
                                    request_id=failed_request_id,
                                    code="upload_too_large",
                                )
                            )
                        except Exception as error:
                            await send_json(
                                _error(
                                    f"Failed to transcribe audio: {error}",
                                    request_id=realtime_session.request_id,
                                    code="transcription_failed",
                                )
                            )
                        continue

                    if temp_file is None:
                        await send_json(
                            _error(
                                "Send a JSON 'start' message before audio data.",
                                code="upload_not_started",
                            )
                        )
                        continue

                    if byte_count + len(binary) > settings.websocket_stt_max_bytes:
                        current_request_id = request_id
                        cleanup_upload()
                        await send_json(
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
                    await send_json(
                        _error(str(error), code="invalid_message")
                    )
                    continue

                message_type = data.get("type")

                if message_type == "start":
                    if realtime_session is not None:
                        await realtime_session.close()
                        realtime_session = None
                    cleanup_upload()
                    request_id = data.get("request_id")
                    audio_format = str(data.get("format", "webm")).lower().lstrip(".")
                    realtime = bool(data.get("realtime", False))
                    supported_formats = allowed_formats | PCM_FORMATS
                    if audio_format not in supported_formats:
                        await send_json(
                            _error(
                                f"Unsupported audio format: {audio_format}. "
                                f"Supported: {sorted(supported_formats)}",
                                request_id=request_id,
                                code="unsupported_format",
                            )
                        )
                        request_id = None
                        continue

                    if audio_format in PCM_FORMATS and not realtime:
                        await send_json(
                            _error(
                                "Raw PCM requires realtime=true.",
                                request_id=request_id,
                                code="invalid_request",
                            )
                        )
                        request_id = None
                        continue

                    if realtime:
                        try:
                            sample_rate = int(data.get("sample_rate", 16000))
                            channels = int(data.get("channels", 1))
                            partial_interval_ms = int(
                                data.get(
                                    "partial_interval_ms",
                                    settings.websocket_stt_partial_interval_ms,
                                )
                            )
                            min_audio_ms = int(
                                data.get(
                                    "min_audio_ms",
                                    settings.websocket_stt_min_audio_ms,
                                )
                            )
                            vad_silence_ms = int(
                                data.get(
                                    "vad_silence_ms",
                                    settings.websocket_stt_vad_silence_ms,
                                )
                            )
                            vad_threshold = float(
                                data.get(
                                    "vad_threshold",
                                    settings.websocket_stt_vad_threshold,
                                )
                            )
                            if sample_rate < 8000 or sample_rate > 48000:
                                raise ValueError("sample_rate must be 8000-48000.")
                            if channels not in {1, 2}:
                                raise ValueError("channels must be 1 or 2.")
                            if partial_interval_ms < 100:
                                raise ValueError(
                                    "partial_interval_ms must be at least 100."
                                )
                            if min_audio_ms < 0:
                                raise ValueError("min_audio_ms cannot be negative.")
                            if vad_silence_ms < 0:
                                raise ValueError("vad_silence_ms cannot be negative.")
                            if not 0 <= vad_threshold <= 1:
                                raise ValueError("vad_threshold must be between 0 and 1.")
                            realtime_session = RealtimeSTTSession(
                                service=stt_service,
                                send_event=send_json,
                                request_id=request_id,
                                audio_format=audio_format,
                                sample_rate=sample_rate,
                                channels=channels,
                                partial_interval_ms=partial_interval_ms,
                                min_audio_ms=min_audio_ms,
                                vad_threshold=vad_threshold,
                                vad_silence_ms=vad_silence_ms,
                            )
                            realtime_session.start()
                        except ValueError as error:
                            realtime_session = None
                            await send_json(
                                _error(
                                    str(error),
                                    request_id=request_id,
                                    code="invalid_request",
                                )
                            )
                            request_id = None
                            continue

                        await send_json(
                            {
                                "type": "ready",
                                "request_id": request_id,
                                "realtime": True,
                                "format": audio_format,
                                "sample_rate": sample_rate,
                                "channels": channels,
                                "partial_interval_ms": realtime_session.partial_interval_ms,
                                "max_bytes": settings.websocket_stt_max_bytes,
                            }
                        )
                        continue

                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=f".{audio_format}",
                    )
                    temp_path = temp_file.name
                    await send_json(
                        {
                            "type": "ready",
                            "request_id": request_id,
                            "realtime": False,
                            "max_bytes": settings.websocket_stt_max_bytes,
                        }
                    )
                    continue

                if message_type == "abort":
                    if realtime_session is not None:
                        aborted_request_id = realtime_session.request_id
                        await realtime_session.close()
                        realtime_session = None
                        request_id = None
                        await send_json(
                            {
                                "type": "aborted",
                                "request_id": aborted_request_id,
                            }
                        )
                        continue
                    aborted_request_id = request_id
                    cleanup_upload()
                    await send_json(
                        {
                            "type": "aborted",
                            "request_id": aborted_request_id,
                        }
                    )
                    continue

                if message_type == "commit":
                    if realtime_session is None:
                        await send_json(
                            _error(
                                "No active realtime audio stream.",
                                request_id=request_id,
                                code="stream_not_started",
                            )
                        )
                    else:
                        try:
                            await realtime_session.transcribe(
                                event_type="partial_transcript",
                                force=True,
                            )
                        except Exception as error:
                            await send_json(
                                _error(
                                    f"Failed to transcribe audio: {error}",
                                    request_id=realtime_session.request_id,
                                    code="transcription_failed",
                                )
                            )
                    continue

                if message_type == "end":
                    if realtime_session is not None:
                        completed_request_id = realtime_session.request_id
                        try:
                            await realtime_session.finish()
                        except ValueError as error:
                            await send_json(
                                _error(
                                    str(error),
                                    request_id=completed_request_id,
                                    code="empty_upload",
                                )
                            )
                        except Exception as error:
                            await send_json(
                                _error(
                                    f"Failed to transcribe audio: {error}",
                                    request_id=completed_request_id,
                                    code="transcription_failed",
                                )
                            )
                        finally:
                            await realtime_session.close()
                            realtime_session = None
                            request_id = None
                        continue

                    if temp_file is None or temp_path is None:
                        await send_json(
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
                        await send_json(
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
                        await send_json(
                            {
                                "type": "transcription",
                                "request_id": completed_request_id,
                                **result,
                            }
                        )
                    except Exception as error:
                        await send_json(
                            _error(
                                f"Failed to transcribe audio: {error}",
                                request_id=completed_request_id,
                                code="transcription_failed",
                            )
                        )
                    finally:
                        cleanup_upload()
                    continue

                await send_json(
                    _error(
                        "STT control message type must be 'start', 'commit', "
                        "'end', or 'abort'.",
                        request_id=request_id,
                        code="invalid_message_type",
                    )
                )
        except WebSocketDisconnect:
            pass
        finally:
            if realtime_session is not None:
                await realtime_session.close()
            cleanup_upload()

    return router
