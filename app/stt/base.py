from typing import Protocol, TypedDict


class STTResult(TypedDict, total=False):
    text: str
    language: str
    engine_used: str
    duration_seconds: float


class STTEngine(Protocol):
    name: str

    def is_available(self) -> bool:
        ...

    def transcribe(self, audio_path: str) -> STTResult:
        ...
