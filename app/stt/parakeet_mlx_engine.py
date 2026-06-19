import os
import shutil
import subprocess
from app.stt.base import STTResult


def _parse_parakeet_output(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return ""

    transcript_lines = []
    for line in lines:
        if line.startswith("[") and "]" in line[:20]:
            continue
        if line.lower().startswith(("loading", "model", "transcribing", "done")):
            continue
        transcript_lines.append(line)

    if transcript_lines:
        return transcript_lines[-1]

    return lines[-1]


class ParakeetMLXEngine:
    name = "parakeet_mlx"

    def __init__(self):
        self.model = os.getenv("PARAKEET_MLX_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
        self.language = os.getenv("STT_LANGUAGE", "en")

    def is_available(self) -> bool:
        return shutil.which("parakeet-mlx") is not None

    def transcribe(self, audio_path: str) -> STTResult:
        cmd = [
            "parakeet-mlx",
            audio_path,
            "--model",
            self.model,
        ]

        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

        text = _parse_parakeet_output(completed.stdout)

        return {
            "text": text,
            "language": self.language,
            "engine_used": self.name,
        }
