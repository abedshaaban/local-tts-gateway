from pathlib import Path
from typing import List
import wave


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
