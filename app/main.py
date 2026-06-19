from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.schemas import TTSRequest, TTSFileResponse
from app.services.tts_service import TTSService
from app.config import settings

app = FastAPI(
    title="Local TTS Gateway",
    description="Local Kokoro-powered text-to-speech service",
    version="0.1.0",
)

tts_service = TTSService()


@app.get("/health")
def health_check():
    return {
        "ok": True,
        "service": "local-tts-gateway",
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
