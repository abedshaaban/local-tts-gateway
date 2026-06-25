import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.services.realtime_stt import PCM_FORMATS, RealtimeSTTSession
from app.services.realtime_tts import RealtimeTTSSession
from app.services.stt_service import STTService
from app.services.tts_service import TTSService


def _error(message: str, code: str = "request_error", request_id=None):
    event = {"type": "error", "code": code, "message": message}
    if request_id is not None:
        event["request_id"] = request_id
    return event


def create_conversation_router(
    tts_service: TTSService,
    stt_service: STTService,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/conversation")
    async def websocket_conversation(websocket: WebSocket):
        await websocket.accept()
        send_lock = asyncio.Lock()
        stt_session: RealtimeSTTSession | None = None
        tts_session: RealtimeTTSSession | None = None
        tts_finish_task: asyncio.Task | None = None
        session_config: dict = {}
        session_id = f"conv_{uuid.uuid4().hex}"

        async def send_json(event: dict):
            async with send_lock:
                await websocket.send_json(event)

        async def send_audio(audio: bytes):
            async with send_lock:
                await websocket.send_bytes(audio)

        async def cancel_response(reason: str, notify: bool = True):
            nonlocal tts_session, tts_finish_task
            active = tts_session
            tts_session = None
            if active is not None:
                await active.cancel(notify=False)
                if notify:
                    await send_json(
                        {
                            "type": "response.cancelled",
                            "response_id": active.request_id,
                            "reason": reason,
                            "chunks": active.chunk_count,
                            "bytes": active.byte_count,
                        }
                    )
            if tts_finish_task is not None:
                tts_finish_task.cancel()
                await asyncio.gather(tts_finish_task, return_exceptions=True)
                tts_finish_task = None

        async def send_stt_event(event: dict):
            event_type = event.get("type")
            if event_type == "speech_started":
                if session_config.get("barge_in", settings.conversation_barge_in):
                    if tts_session is not None:
                        interrupted_id = tts_session.request_id
                        await cancel_response("barge_in", notify=False)
                        await send_json(
                            {
                                "type": "response.interrupted",
                                "response_id": interrupted_id,
                                "reason": "barge_in",
                            }
                        )
                await send_json(
                    {
                        **event,
                        "type": "input_audio_buffer.speech_started",
                    }
                )
                return
            if event_type == "speech_stopped":
                await send_json(
                    {
                        **event,
                        "type": "input_audio_buffer.speech_stopped",
                    }
                )
                return
            if event_type == "partial_transcript":
                await send_json(
                    {
                        **event,
                        "type": "conversation.transcript.partial",
                    }
                )
                return
            if event_type == "final_transcript":
                await send_json(
                    {
                        **event,
                        "type": "conversation.transcript.final",
                    }
                )
                return
            await send_json(event)

        async def create_stt(config: dict):
            nonlocal stt_session
            if stt_session is not None:
                await stt_session.close()

            audio_format = str(config.get("format", "pcm_s16le")).lower()
            if audio_format not in PCM_FORMATS:
                raise ValueError(
                    "Conversation audio input currently requires pcm_s16le."
                )
            sample_rate = int(config.get("sample_rate", 16000))
            channels = int(config.get("channels", 1))
            partial_interval_ms = int(
                config.get(
                    "partial_interval_ms",
                    settings.websocket_stt_partial_interval_ms,
                )
            )
            min_audio_ms = int(
                config.get(
                    "min_audio_ms",
                    settings.websocket_stt_min_audio_ms,
                )
            )
            vad_threshold = float(
                config.get(
                    "vad_threshold",
                    settings.websocket_stt_vad_threshold,
                )
            )
            vad_silence_ms = int(
                config.get(
                    "vad_silence_ms",
                    settings.websocket_stt_vad_silence_ms,
                )
            )
            rolling_window_ms = int(
                config.get(
                    "rolling_window_ms",
                    settings.websocket_stt_rolling_window_ms,
                )
            )
            if sample_rate < 8000 or sample_rate > 48000:
                raise ValueError("sample_rate must be 8000-48000.")
            if channels not in {1, 2}:
                raise ValueError("channels must be 1 or 2.")
            if partial_interval_ms < 100:
                raise ValueError("partial_interval_ms must be at least 100.")
            if min_audio_ms < 0:
                raise ValueError("min_audio_ms cannot be negative.")
            if not 0 <= vad_threshold <= 1:
                raise ValueError("vad_threshold must be between 0 and 1.")
            if vad_silence_ms < 0:
                raise ValueError("vad_silence_ms cannot be negative.")
            if rolling_window_ms < 1000:
                raise ValueError("rolling_window_ms must be at least 1000.")

            stt_session = RealtimeSTTSession(
                service=stt_service,
                send_event=send_stt_event,
                request_id=session_id,
                audio_format=audio_format,
                sample_rate=sample_rate,
                channels=channels,
                partial_interval_ms=partial_interval_ms,
                min_audio_ms=min_audio_ms,
                vad_threshold=vad_threshold,
                vad_silence_ms=vad_silence_ms,
                rolling_window_ms=rolling_window_ms,
            )
            stt_session.start()

        async def send_tts_event(event: dict):
            event_type = event.get("type")
            mapping = {
                "segment_start": "response.audio.segment_start",
                "segment_complete": "response.audio.segment_complete",
                "complete": "response.audio.done",
                "cancelled": "response.cancelled",
            }
            await send_json({**event, "type": mapping.get(event_type, event_type)})

        async def start_response(data: dict):
            nonlocal tts_session
            if tts_session is not None:
                await cancel_response("superseded")

            response_id = data.get("response_id") or f"resp_{uuid.uuid4().hex}"
            tts_session = RealtimeTTSSession(
                service=tts_service,
                send_event=send_tts_event,
                send_audio=send_audio,
                request_id=response_id,
                voice=str(
                    data.get(
                        "voice",
                        session_config.get("voice", settings.default_voice),
                    )
                ),
                speed=float(
                    data.get(
                        "speed",
                        session_config.get("speed", settings.default_speed),
                    )
                ),
                lang_code=str(
                    data.get(
                        "lang_code",
                        session_config.get("lang_code", settings.default_lang_code),
                    )
                ),
                split_pattern=str(data.get("split_pattern", r"\n+")),
            )
            await send_json(
                {
                    "type": "response.created",
                    "response_id": response_id,
                    "format": "float32le",
                    "sample_rate": settings.sample_rate,
                    "channels": 1,
                }
            )
            return tts_session

        async def finish_response(active: RealtimeTTSSession):
            nonlocal tts_session, tts_finish_task
            try:
                await active.finish()
            finally:
                if tts_session is active:
                    tts_session = None
                tts_finish_task = None

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                audio = message.get("bytes")
                if audio is not None:
                    if stt_session is None:
                        await send_json(
                            _error(
                                "Send session.start before audio.",
                                code="session_not_started",
                            )
                        )
                        continue
                    try:
                        await stt_session.append(audio)
                    except Exception as error:
                        await send_json(
                            _error(
                                f"Failed to process audio: {error}",
                                code="audio_input_failed",
                            )
                        )
                    continue

                text = message.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("Event must be a JSON object.")
                except (json.JSONDecodeError, ValueError) as error:
                    await send_json(_error(str(error), code="invalid_event"))
                    continue

                event_type = data.get("type")
                try:
                    if event_type == "session.start":
                        session_config = {
                            **session_config,
                            **data.get("config", {}),
                        }
                        await create_stt(session_config)
                        await send_json(
                            {
                                "type": "session.ready",
                                "session_id": session_id,
                                "input_format": "pcm_s16le",
                                "input_sample_rate": stt_session.sample_rate,
                                "output_format": "float32le",
                                "output_sample_rate": settings.sample_rate,
                                "barge_in": session_config.get(
                                    "barge_in",
                                    settings.conversation_barge_in,
                                ),
                            }
                        )
                    elif event_type == "input_audio_buffer.commit":
                        if stt_session is None:
                            raise ValueError("The session has not started.")
                        await stt_session.transcribe(
                            event_type="partial_transcript",
                            force=True,
                        )
                    elif event_type == "input_audio_buffer.clear":
                        await create_stt(session_config)
                        await send_json({"type": "input_audio_buffer.cleared"})
                    elif event_type in {"response.start", "response.create"}:
                        if event_type == "response.create":
                            text_input = data.get("text", "")
                            if not isinstance(text_input, str) or not text_input:
                                raise ValueError("response.create requires non-empty text.")
                        active = await start_response(data)
                        if event_type == "response.create":
                            await active.append_text(text_input)
                            tts_finish_task = asyncio.create_task(
                                finish_response(active)
                            )
                    elif event_type == "response.text.delta":
                        if tts_session is None:
                            raise ValueError("No active response.")
                        delta = data.get("text", data.get("delta", ""))
                        if not isinstance(delta, str):
                            raise ValueError("Text delta must be a string.")
                        await tts_session.append_text(delta)
                    elif event_type == "response.text.done":
                        if tts_session is None:
                            raise ValueError("No active response.")
                        if tts_finish_task is None:
                            tts_finish_task = asyncio.create_task(
                                finish_response(tts_session)
                            )
                    elif event_type == "response.flush":
                        if tts_session is None:
                            raise ValueError("No active response.")
                        await tts_session.flush()
                    elif event_type == "response.cancel":
                        await cancel_response("client_cancelled")
                    elif event_type == "session.end":
                        if stt_session is not None and stt_session.byte_count:
                            await stt_session.finish()
                        await send_json(
                            {
                                "type": "session.closed",
                                "session_id": session_id,
                            }
                        )
                        break
                    else:
                        await send_json(
                            _error(
                                "Unsupported conversation event type.",
                                code="invalid_event_type",
                            )
                        )
                except ValueError as error:
                    await send_json(_error(str(error), code="invalid_request"))
                except Exception as error:
                    await send_json(
                        _error(str(error), code="conversation_error")
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await cancel_response("connection_closed", notify=False)
            if stt_session is not None:
                await stt_session.close()

    return router
