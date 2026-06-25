import asyncio
import shutil
import tempfile
import time
from pathlib import Path

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

from app.audio_output import MEDIA_TYPES, convert_wav, float32_to_s16le, remove_file
from app.config import settings
from app.model_registry import (
    ModelCapabilityError,
    ModelNotFoundError,
    ModelRegistry,
    SPEECH_TO_TEXT,
    TEXT_TO_SPEECH,
    VoiceNotFoundError,
)
from app.services.stt_service import STTService
from app.services.tts_service import TTSService


class OpenAISpeechRequest(BaseModel):
    model: str = settings.default_tts_model
    input: str = Field(..., min_length=1, max_length=20_000)
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    instructions: str | None = Field(default=None, max_length=4096)
    stream_format: str = "audio"


def create_openai_compat_router(
    tts_service: TTSService,
    stt_service: STTService,
    registry: ModelRegistry,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/models")
    def list_models():
        created = int(time.time())
        models = []
        for model in registry.list_models():
            models.append(
                {
                    "id": model.id,
                    "object": "model",
                    "created": created,
                    "owned_by": model.owned_by,
                }
            )
        return {"object": "list", "data": models}

    @router.get("/models/{model_id}")
    def retrieve_model(model_id: str):
        try:
            model = registry.resolve_model(model_id)
        except ModelNotFoundError:
            raise HTTPException(status_code=404, detail="Model not found.")
        return {
            "id": model.id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": model.owned_by,
        }

    @router.post("/audio/speech")
    def create_speech(
        payload: OpenAISpeechRequest,
        background_tasks: BackgroundTasks,
    ):
        try:
            registry.resolve_model(payload.model, TEXT_TO_SPEECH)
            registry.resolve_voice(payload.voice, payload.model)
        except (ModelNotFoundError, ModelCapabilityError, VoiceNotFoundError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
        if payload.stream_format != "audio":
            raise HTTPException(
                status_code=400,
                detail="Only stream_format=audio is currently supported.",
            )
        response_format = payload.response_format.lower()
        if response_format not in MEDIA_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported response_format: {response_format}",
            )

        if response_format == "pcm":
            return StreamingResponse(
                float32_to_s16le(
                    tts_service.stream_pcm(
                        text=payload.input,
                        voice=payload.voice,
                        speed=payload.speed,
                        lang_code=settings.default_lang_code,
                        model=payload.model,
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
                voice=payload.voice,
                speed=payload.speed,
                lang_code=settings.default_lang_code,
                model=payload.model,
            )
            output_path = wav_path
            if response_format != "wav":
                output_path = convert_wav(wav_path, response_format)
                background_tasks.add_task(remove_file, wav_path)
            background_tasks.add_task(remove_file, output_path)
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
        model: str = Form(settings.default_stt_model),
        language: str | None = Form(None),
        prompt: str | None = Form(None),
        response_format: str = Form("json"),
        temperature: float = Form(0),
    ):
        del temperature
        try:
            registry.resolve_model(model, SPEECH_TO_TEXT)
        except (ModelNotFoundError, ModelCapabilityError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
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
                model,
            )
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to transcribe audio: {error}",
            ) from error
        finally:
            if temp_path:
                remove_file(temp_path)

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
