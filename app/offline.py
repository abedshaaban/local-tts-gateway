import os

from app.config import settings


def configure_offline_runtime() -> None:
    """
    Configure Hugging Face / Transformers offline behavior.

    When KOKORO_LOCAL_ONLY=true:
    - Do not contact Hugging Face Hub.
    - Use local cached files only.
    """
    os.environ["HF_HOME"] = str(settings.hf_home)

    if settings.kokoro_local_only:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
