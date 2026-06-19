import os
import subprocess
from pathlib import Path
from app.stt.base import STTResult


def _parse_whisper_cpp_output(stdout: str) -> str:
    lines = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and "]" in stripped[:30]:
            continue
        if stripped.lower().startswith(("whisper_", "system_info", "main:")):
            continue
        lines.append(stripped)

    return " ".join(lines).strip()


class WhisperCppEngine:
    name = "whisper_cpp"

    def __init__(self):
        self.bin_path = os.getenv("WHISPER_CPP_BIN", "./vendor/whisper.cpp/build/bin/whisper-cli")
        self.model_path = os.getenv("WHISPER_CPP_MODEL", "./models/whisper/ggml-large-v3-turbo.bin")
        self.language = os.getenv("STT_LANGUAGE", "en")

    def is_available(self) -> bool:
        return Path(self.bin_path).exists() and Path(self.model_path).exists()

    def transcribe(self, audio_path: str) -> STTResult:
        cmd = [
            self.bin_path,
            "-m",
            self.model_path,
            "-f",
            audio_path,
            "-l",
            self.language,
            "-nt",
        ]

        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

        text = _parse_whisper_cpp_output(completed.stdout)

        return {
            "text": text,
            "language": self.language,
            "engine_used": self.name,
        }
