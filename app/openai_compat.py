import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.services.stt_service import STTService
from app.services.tts_service import TTSService


TTS_MODEL_ALIASES = {
    "local-tts",
    "tts-1",
    "tts-1-hd",
    "gpt-4o-mini-tts",
}
STT_MODEL_ALIASES = {
    "local-stt",
    "whisper-1",
    "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe",
}
VOICE_ALIASES = {
    "alloy": "af_heart",
    "ash": "am_adam",
    "ballad": "af_bella",
    "coral": "af_sarah",
    "echo": "am_michael",
    "fable": "af_bella",
    "nova": "af_sarah",
    "onyx": "am_adam",
    "sage": "af_heart",
    "shimmer": "af_bella",
    "verse": "am_michael",
    "marin": "af_heart",
    "cedar": "am_michael",
}
MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "application/octet-stream",
}


class OpenAISpeechRequest(BaseModel):
    model: str = "local-tts"
    input: str = Field(..., min_length=1, max_length=20_000)
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    instructions: str | None = None


def _remove_file(path: str | Path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _float32_to_s16le(chunks):
    for chunk in chunks:
        samples = np.frombuffer(chunk, dtype=np.float32)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
        yield pcm.tobytes()


def _convert_wav(input_path: Path, response_format: str) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            f"ffmpeg is required for response_format={response_format}."
        )

    output = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=f".{response_format}",
    )
    output.close()
    codec_args = {
        "mp3": ["-codec:a", "libmp3lame"],
        "opus": ["-codec:a", "libopus", "-f", "opus"],
        "aac": ["-codec:a", "aac", "-f", "adts"],
        "flac": ["-codec:a", "flac"],
    }[response_format]
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), *codec_args, output.name],
        check=True,
        capture_output=True,
    )
    return Path(output.name)


def create_openai_compat_router(
    tts_service: TTSService,
    stt_service: STTService,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/models")
    def list_models():
        created = int(time.time())
        models = [
            {
                "id": "local-tts",
                "object": "model",
                "created": created,
                "owned_by": "local",
            },
            {
                "id": "local-stt",
                "object": "model",
                "created": created,
                "owned_by": "local",
            },
        ]
        return {"object": "list", "data": models}

    @router.get("/models/{model_id}")
    def retrieve_model(model_id: str):
        if model_id not in TTS_MODEL_ALIASES | STT_MODEL_ALIASES:
            raise HTTPException(status_code=404, detail="Model not found.")
        canonical = "local-tts" if model_id in TTS_MODEL_ALIASES else "local-stt"
        return {
            "id": canonical,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local",
        }

    @router.post("/audio/speech")
    def create_speech(
        payload: OpenAISpeechRequest,
        background_tasks: BackgroundTasks,
    ):
        if payload.model not in TTS_MODEL_ALIASES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported speech model: {payload.model}",
            )
        response_format = payload.response_format.lower()
        if response_format not in MEDIA_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported response_format: {response_format}",
            )

        voice = VOICE_ALIASES.get(payload.voice, payload.voice)
        if response_format == "pcm":
            return StreamingResponse(
                _float32_to_s16le(
                    tts_service.stream_pcm(
                        text=payload.input,
                        voice=voice,
                        speed=payload.speed,
                        lang_code=settings.default_lang_code,
                    )
                ),
                media_type=MEDIA_TYPES[response_format],
                headers={
                    "X-Audio-Format": "pcm_s16le",
                    "X-Audio-Sample-Rate": str(settings.sample_rate),
                    "X-Audio-Channels": "1",
                    "X-Local-Instructions-Ignored": str(
                        bool(payload.instructions)
                    ).lower(),
                },
            )

        try:
            wav_path = tts_service.generate_wav(
                text=payload.input,
                voice=voice,
                speed=payload.speed,
                lang_code=settings.default_lang_code,
            )
            output_path = wav_path
            if response_format != "wav":
                output_path = _convert_wav(wav_path, response_format)
                background_tasks.add_task(_remove_file, wav_path)
            background_tasks.add_task(_remove_file, output_path)
            return FileResponse(
                output_path,
                media_type=MEDIA_TYPES[response_format],
                filename=f"speech.{response_format}",
                background=background_tasks,
                headers={
                    "X-Local-Instructions-Ignored": str(
                        bool(payload.instructions)
                    ).lower(),
                },
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate speech: {error}",
            ) from error

    @router.post("/audio/transcriptions")
    async def create_transcription(
        file: UploadFile = File(...),
        model: str = Form("local-stt"),
        language: str | None = Form(None),
        prompt: str | None = Form(None),
        response_format: str = Form("json"),
        temperature: float = Form(0),
    ):
        del temperature
        if model not in STT_MODEL_ALIASES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported transcription model: {model}",
            )
        response_format = response_format.lower()
        if response_format not in {"json", "text", "verbose_json"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Supported transcription response formats are "
                    "json, text, and verbose_json."
                ),
            )

        suffix = Path(file.filename or "audio.wav").suffix or ".wav"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                shutil.copyfileobj(file.file, temp)
                temp_path = temp.name
            result = await asyncio.to_thread(
                stt_service.transcribe_file,
                temp_path,
            )
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to transcribe audio: {error}",
            ) from error
        finally:
            if temp_path:
                _remove_file(temp_path)

        text = result.get("text", "")
        headers = {
            "X-Local-Prompt-Ignored": str(bool(prompt)).lower(),
            "X-Local-Language-Hint-Ignored": str(bool(language)).lower(),
        }
        if response_format == "text":
            return PlainTextResponse(text, headers=headers)
        if response_format == "verbose_json":
            return JSONResponse(
                {
                    "task": "transcribe",
                    "language": result.get("language", language or "en"),
                    "duration": result.get("duration_seconds", 0),
                    "text": text,
                    "segments": [],
                    "engine_used": result.get("engine_used"),
                },
                headers=headers,
            )
        return JSONResponse({"text": text}, headers=headers)

    return router
