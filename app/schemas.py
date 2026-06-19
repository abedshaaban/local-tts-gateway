from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)
    voice: str = "af_heart"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    lang_code: str = "a"


class TTSFileResponse(BaseModel):
    filename: str
    path: str
