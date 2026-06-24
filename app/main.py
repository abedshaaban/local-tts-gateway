import logging
import subprocess
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
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings
from app.offline import configure_offline_runtime

configure_offline_runtime()

from app.schemas import TTSRequest, TTSFileResponse, STTResponse
from app.services.tts_service import TTSService
from app.services.stt_service import STTService
from app.websocket_routes import create_websocket_router

app = FastAPI(
    title="Local TTS Gateway",
    description="Local Kokoro-powered text-to-speech and speech-to-text service",
    version="0.2.0",
)

tts_service = TTSService()
stt_service = STTService()
app.include_router(create_websocket_router(tts_service, stt_service))


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
    }


@app.get("/voices")
def get_voices():
    return {
        "default": settings.default_voice,
        "examples": [
            "af_heart",
            "af_bella",
            "af_sarah",
            "am_adam",
            "am_michael",
        ],
        "note": "Voice availability depends on the Kokoro version/model installed.",
    }


@app.post("/tts/wav")
def generate_tts_wav(payload: TTSRequest):
    try:
        output_path = tts_service.generate_wav(
            text=payload.text,
            voice=payload.voice,
            speed=payload.speed,
            lang_code=payload.lang_code,
            split_pattern=payload.split_pattern,
        )

        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename="speech.wav",
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
async def speech_to_text(audio: UploadFile = File(...)):
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

        result = stt_service.transcribe_file(temp_path)
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
        )

        background_tasks.add_task(subprocess.run, ["afplay", str(output_path)])

        return {
            "ok": True,
            "path": str(output_path),
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to play speech: {str(error)}",
        )
