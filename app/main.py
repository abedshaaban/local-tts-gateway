import logging
import subprocess
import uuid
import warnings

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r".*dropout option adds dropout.*",
)
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message=r".*weight_norm.*deprecated.*",
)


def _configure_app_logging() -> None:
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


_configure_app_logging()

import os
import shutil
import tempfile

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.offline import configure_offline_runtime

configure_offline_runtime()

from app.schemas import TTSRequest, TTSFileResponse, STTResponse
from app.services.tts_service import TTSService
from app.services.stt_service import STTService
from app.conversation_routes import create_conversation_router
from app.audio_output import remove_file
from app.elevenlabs_compat import create_elevenlabs_compat_router
from app.model_registry import build_default_registry
from app.openai_compat import create_openai_compat_router
from app.websocket_routes import create_websocket_router

app = FastAPI(
    title="Local TTS Gateway",
    description="Local Kokoro-powered text-to-speech and speech-to-text service",
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

model_registry = build_default_registry(settings.enabled_models)
tts_service = TTSService(model_registry)
stt_service = STTService(model_registry)
app.include_router(create_websocket_router(tts_service, stt_service))
app.include_router(create_conversation_router(tts_service, stt_service))
app.include_router(
    create_openai_compat_router(tts_service, stt_service, model_registry)
)
app.include_router(create_elevenlabs_compat_router(tts_service, model_registry))


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers.setdefault("x-request-id", request_id)
    return response


@app.get("/health")
def health_check():
    return {
        "ok": True,
        "service": "local-tts-gateway",
    }


@app.get("/runtime")
def runtime_info():
    return {
        "kokoro_repo_id": settings.kokoro_repo_id,
        "kokoro_local_only": settings.kokoro_local_only,
        "hf_home": str(settings.hf_home),
        "output_dir": str(settings.output_dir),
        "sample_rate": settings.sample_rate,
        "websocket_stt_max_bytes": settings.websocket_stt_max_bytes,
        "websocket_stt_partial_interval_ms": settings.websocket_stt_partial_interval_ms,
        "websocket_stt_min_audio_ms": settings.websocket_stt_min_audio_ms,
        "websocket_stt_rolling_window_ms": settings.websocket_stt_rolling_window_ms,
        "websocket_tts_max_buffer_chars": settings.websocket_tts_max_buffer_chars,
        "conversation_barge_in": settings.conversation_barge_in,
        "cors_allow_origin_regex": settings.cors_allow_origin_regex,
        "default_tts_model": settings.default_tts_model,
        "default_stt_model": settings.default_stt_model,
        "enabled_models": [model.id for model in model_registry.list_models()],
        "save_generated_audio": settings.save_generated_audio,
        "save_transcriptions": settings.save_transcriptions,
    }


@app.get("/voices")
def get_voices():
    return {
        "default": settings.default_voice,
        "voices": [
            {
                "id": voice.id,
                "name": voice.name,
                "aliases": sorted(voice.aliases),
                "model_ids": sorted(voice.model_ids),
            }
            for voice in model_registry.list_voices()
        ],
        "note": "Voice availability depends on the Kokoro version/model installed.",
    }


@app.post("/tts/wav")
def generate_tts_wav(payload: TTSRequest, background_tasks: BackgroundTasks):
    try:
        output_path = tts_service.generate_wav(
            text=payload.text,
            voice=payload.voice,
            speed=payload.speed,
            lang_code=payload.lang_code,
            split_pattern=payload.split_pattern,
            model=payload.model,
        )

        if not settings.save_generated_audio:
            background_tasks.add_task(remove_file, output_path)
        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename="speech.wav",
            background=background_tasks,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate speech: {str(error)}",
        )


@app.post("/tts/file", response_model=TTSFileResponse)
def generate_tts_file(payload: TTSRequest):
    try:
        output_path = tts_service.generate_wav(
            text=payload.text,
            voice=payload.voice,
            speed=payload.speed,
            lang_code=payload.lang_code,
            split_pattern=payload.split_pattern,
            model=payload.model,
        )

        return TTSFileResponse(
            filename=output_path.name,
            path=str(output_path),
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate speech file: {str(error)}",
        )


@app.post("/tts/stream")
def stream_tts_wav(payload: TTSRequest):
    try:
        return StreamingResponse(
            tts_service.stream_wav(
                text=payload.text,
                voice=payload.voice,
                speed=payload.speed,
                lang_code=payload.lang_code,
                split_pattern=payload.split_pattern,
                model=payload.model,
            ),
            media_type="audio/wav",
            headers={
                "Content-Disposition": 'inline; filename="speech-stream.wav"',
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stream speech: {str(error)}",
        )


@app.post("/tts/stream/pcm")
def stream_tts_pcm(payload: TTSRequest):
    try:
        return StreamingResponse(
            tts_service.stream_pcm(
                text=payload.text,
                voice=payload.voice,
                speed=payload.speed,
                lang_code=payload.lang_code,
                split_pattern=payload.split_pattern,
                model=payload.model,
            ),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'inline; filename="speech-stream.pcm"',
                "Cache-Control": "no-cache",
                "X-Audio-Sample-Rate": str(settings.sample_rate),
                "X-Audio-Format": "float32le",
                "X-Audio-Channels": "1",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stream PCM speech: {str(error)}",
        )


@app.post("/stt/text", response_model=STTResponse)
async def speech_to_text(
    audio: UploadFile = File(...),
    model: str = Form(settings.default_stt_model),
):
    suffix = "wav"
    if audio.filename and "." in audio.filename:
        suffix = audio.filename.rsplit(".", 1)[-1].lower()

    allowed = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "webm"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {suffix}. Supported: {sorted(allowed)}",
        )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as temp:
            shutil.copyfileobj(audio.file, temp)
            temp_path = temp.name

        result = stt_service.transcribe_file(temp_path, model=model)
        stt_service.save_transcription(result, model=model)
        return result

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/tts/play")
def play_tts(payload: TTSRequest, background_tasks: BackgroundTasks):
    try:
        output_path = tts_service.generate_wav(
            text=payload.text,
            voice=payload.voice,
            speed=payload.speed,
            lang_code=payload.lang_code,
            split_pattern=payload.split_pattern,
            model=payload.model,
        )

        background_tasks.add_task(subprocess.run, ["afplay", str(output_path)])
        if not settings.save_generated_audio:
            background_tasks.add_task(remove_file, output_path)

        return {
            "ok": True,
            "path": str(output_path),
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to play speech: {str(error)}",
        )
