from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audio_output import (
    MEDIA_TYPES,
    convert_wav,
    float32_to_s16le,
    iter_file,
    remove_file,
)
from app.config import settings
from app.model_registry import (
    ModelCapabilityError,
    ModelNotFoundError,
    ModelRegistry,
    TEXT_TO_SPEECH,
    VoiceNotFoundError,
)
from app.services.tts_service import TTSService


class ElevenLabsVoiceSettings(BaseModel):
    stability: float | None = None
    similarity_boost: float | None = None
    style: float | None = None
    use_speaker_boost: bool | None = None
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class ElevenLabsSpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)
    model_id: str = settings.default_tts_model
    language_code: str | None = None
    voice_settings: ElevenLabsVoiceSettings | None = None
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    previous_text: str | None = None
    next_text: str | None = None
    previous_request_ids: list[str] | None = None
    next_request_ids: list[str] | None = None


def _parse_output_format(output_format: str) -> tuple[str, int | None, int | None]:
    parts = output_format.lower().split("_")
    codec = parts[0]
    if codec not in {"mp3", "opus", "aac", "flac", "wav", "pcm"}:
        raise ValueError(f"Unsupported output_format: {output_format}")

    sample_rate = None
    bitrate = None
    if len(parts) > 1:
        try:
            sample_rate = int(parts[1])
        except ValueError as error:
            raise ValueError(f"Invalid output_format: {output_format}") from error
    if len(parts) > 2:
        try:
            bitrate = int(parts[2])
        except ValueError as error:
            raise ValueError(f"Invalid output_format: {output_format}") from error
    return codec, sample_rate, bitrate


def _voice_response(voice):
    return {
        "voice_id": voice.id,
        "name": voice.name,
        "samples": None,
        "category": voice.category,
        "fine_tuning": None,
        "labels": voice.labels,
        "description": voice.description,
        "preview_url": None,
        "available_for_tiers": ["local"],
        "settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0,
            "use_speaker_boost": False,
            "speed": 1,
        },
        "sharing": None,
        "high_quality_base_model_ids": sorted(voice.model_ids),
        "verified_languages": [
            {
                "language": voice.language,
                "model_id": model_id,
                "accent": None,
                "locale": voice.language,
                "preview_url": None,
            }
            for model_id in sorted(voice.model_ids)
        ],
        "collection_ids": [],
        "is_owner": True,
        "is_legacy": False,
        "is_mixed": False,
    }


def create_elevenlabs_compat_router(
    tts_service: TTSService,
    registry: ModelRegistry,
) -> APIRouter:
    router = APIRouter()

    def create_audio_response(
        voice_id: str,
        payload: ElevenLabsSpeechRequest,
        output_format: str,
        background_tasks: BackgroundTasks,
        *,
        stream: bool,
    ):
        try:
            registry.resolve_model(payload.model_id, TEXT_TO_SPEECH)
            registry.resolve_voice(voice_id, payload.model_id)
            codec, sample_rate, bitrate = _parse_output_format(output_format)
        except (
            ModelNotFoundError,
            ModelCapabilityError,
            VoiceNotFoundError,
            ValueError,
        ) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        speed = payload.voice_settings.speed if payload.voice_settings else 1.0
        headers = {
            "request-id": str(uuid.uuid4()),
            "character-cost": str(len(payload.text)),
            "X-Local-Seed-Ignored": str(payload.seed is not None).lower(),
            "X-Local-Context-Ignored": str(
                bool(
                    payload.previous_text
                    or payload.next_text
                    or payload.previous_request_ids
                    or payload.next_request_ids
                )
            ).lower(),
        }

        if codec == "pcm":
            if sample_rate not in {None, settings.sample_rate}:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"PCM output is available at {settings.sample_rate} Hz; "
                        f"requested {sample_rate} Hz."
                    ),
                )
            return StreamingResponse(
                float32_to_s16le(
                    tts_service.stream_pcm(
                        text=payload.text,
                        voice=voice_id,
                        speed=speed,
                        lang_code=settings.default_lang_code,
                        model=payload.model_id,
                    )
                ),
                media_type=MEDIA_TYPES["pcm"],
                headers={
                    **headers,
                    "X-Audio-Format": "pcm_s16le",
                    "X-Audio-Sample-Rate": str(settings.sample_rate),
                    "X-Audio-Channels": "1",
                },
            )

        try:
            wav_path = tts_service.generate_wav(
                text=payload.text,
                voice=voice_id,
                speed=speed,
                lang_code=settings.default_lang_code,
                model=payload.model_id,
            )
            output_path = wav_path
            if codec != "wav" or (
                sample_rate is not None and sample_rate != settings.sample_rate
            ):
                output_path = convert_wav(
                    Path(wav_path),
                    codec,
                    sample_rate=sample_rate,
                    bitrate_kbps=bitrate,
                    output_dir=(
                        settings.output_dir
                        if settings.save_generated_audio
                        else None
                    ),
                )
                background_tasks.add_task(remove_file, wav_path)
            if not settings.save_generated_audio:
                background_tasks.add_task(remove_file, output_path)
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate speech: {error}",
            ) from error

        if stream:
            return StreamingResponse(
                iter_file(Path(output_path)),
                media_type=MEDIA_TYPES[codec],
                headers=headers,
                background=background_tasks,
            )
        return FileResponse(
            output_path,
            media_type=MEDIA_TYPES[codec],
            filename=f"speech.{codec}",
            headers=headers,
            background=background_tasks,
        )

    @router.post("/v1/text-to-speech/{voice_id}")
    def create_speech(
        voice_id: str,
        payload: ElevenLabsSpeechRequest,
        background_tasks: BackgroundTasks,
        output_format: str = Query("mp3_44100_128"),
    ):
        return create_audio_response(
            voice_id,
            payload,
            output_format,
            background_tasks,
            stream=False,
        )

    @router.post("/v1/text-to-speech/{voice_id}/stream")
    def stream_speech(
        voice_id: str,
        payload: ElevenLabsSpeechRequest,
        background_tasks: BackgroundTasks,
        output_format: str = Query("mp3_44100_128"),
    ):
        return create_audio_response(
            voice_id,
            payload,
            output_format,
            background_tasks,
            stream=True,
        )

    def list_voices_response(
        page_size: int,
        search: str | None,
        model_id: str | None,
    ):
        try:
            voices = registry.list_voices(model_id)
        except (ModelNotFoundError, ModelCapabilityError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if search:
            query = search.lower()
            voices = [
                voice
                for voice in voices
                if query in voice.id.lower() or query in voice.name.lower()
            ]
        selected = voices[:page_size]
        return {
            "voices": [_voice_response(voice) for voice in selected],
            "has_more": len(voices) > len(selected),
            "total_count": len(voices),
            "next_page_token": None,
        }

    @router.get("/v1/voices")
    @router.get("/v2/voices")
    def list_voices(
        page_size: int = Query(10, ge=1, le=100),
        search: str | None = None,
        model_id: str | None = None,
    ):
        return list_voices_response(page_size, search, model_id)

    @router.get("/v1/voices/{voice_id}")
    def get_voice(voice_id: str):
        try:
            return _voice_response(registry.resolve_voice(voice_id))
        except VoiceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/elevenlabs/v1/models")
    def list_elevenlabs_models():
        return [
            {
                "model_id": model.id,
                "name": model.name or model.id,
                "can_do_text_to_speech": True,
                "can_do_voice_conversion": False,
                "can_be_finetuned": False,
                "can_use_style": False,
                "can_use_speaker_boost": False,
                "serves_pro_voices": False,
                "token_cost_factor": 0,
                "description": model.description,
                "languages": [],
                "max_characters_request_free_user": 20_000,
                "max_characters_request_subscribed_user": 20_000,
                "requires_alpha_access": False,
            }
            for model in registry.list_models(TEXT_TO_SPEECH)
        ]

    return router
