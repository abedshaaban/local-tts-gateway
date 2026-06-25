import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np


MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "application/octet-stream",
}


def remove_file(path: str | Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def float32_to_s16le(chunks):
    for chunk in chunks:
        samples = np.frombuffer(chunk, dtype=np.float32)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
        yield pcm.tobytes()


def convert_wav(
    input_path: Path,
    response_format: str,
    *,
    sample_rate: int | None = None,
    bitrate_kbps: int | None = None,
) -> Path:
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
        "wav": ["-codec:a", "pcm_s16le"],
    }[response_format]
    if sample_rate:
        codec_args.extend(["-ar", str(sample_rate)])
    if bitrate_kbps:
        codec_args.extend(["-b:a", f"{bitrate_kbps}k"])
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), *codec_args, output.name],
        check=True,
        capture_output=True,
    )
    return Path(output.name)


def iter_file(path: Path, chunk_size: int = 64 * 1024):
    with path.open("rb") as audio:
        while chunk := audio.read(chunk_size):
            yield chunk
