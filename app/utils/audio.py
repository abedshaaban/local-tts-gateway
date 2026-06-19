from pathlib import Path
from typing import List
from io import BytesIO
import wave

import numpy as np
import soundfile as sf

from app.config import settings


def combine_wav_files(input_files: List[Path], output_file: Path) -> Path:
    if not input_files:
        raise ValueError("No input files provided")

    if len(input_files) == 1:
        return input_files[0]

    with wave.open(str(input_files[0]), "rb") as first_wav:
        params = first_wav.getparams()

    with wave.open(str(output_file), "wb") as output_wav:
        output_wav.setparams(params)

        for file in input_files:
            with wave.open(str(file), "rb") as input_wav:
                output_wav.writeframes(input_wav.readframes(input_wav.getnframes()))

    return output_file


def normalize_audio_array(audio) -> np.ndarray:
    """
    Convert Kokoro audio output to a clean NumPy float32 array.

    Kokoro may return:
    - NumPy array
    - PyTorch tensor
    - list-like audio data

    This function normalizes it to:
    - NumPy ndarray
    - dtype float32
    - mono shape
    """
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()

    audio = np.asarray(audio, dtype=np.float32)

    if audio.ndim > 1:
        audio = audio.squeeze()

    return audio


def audio_array_to_wav_bytes(audio) -> bytes:
    audio = normalize_audio_array(audio)

    buffer = BytesIO()
    sf.write(buffer, audio, settings.sample_rate, format="WAV")
    buffer.seek(0)

    return buffer.read()


def audio_array_to_pcm_bytes(audio) -> bytes:
    audio = normalize_audio_array(audio)
    return audio.tobytes()
