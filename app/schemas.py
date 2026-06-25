from typing import Optional

from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    model: str | None = None
    text: str = Field(..., min_length=1, max_length=20_000)
    voice: str = "af_heart"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    lang_code: str = "a"
    split_pattern: str = r"\n+"


class TTSFileResponse(BaseModel):
    filename: str
    path: str


class STTResponse(BaseModel):
    text: str
    language: str = "en"
    engine_used: Optional[str] = None
    duration_seconds: float
