from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


TEXT_TO_SPEECH = "text_to_speech"
SPEECH_TO_TEXT = "speech_to_text"


class ModelRegistryError(ValueError):
    pass


class ModelNotFoundError(ModelRegistryError):
    pass


class ModelCapabilityError(ModelRegistryError):
    pass


class VoiceNotFoundError(ModelRegistryError):
    pass


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    provider: str
    capabilities: frozenset[str]
    aliases: frozenset[str] = frozenset()
    owned_by: str = "local"
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class VoiceDefinition:
    id: str
    name: str
    provider: str
    model_ids: frozenset[str]
    aliases: frozenset[str] = frozenset()
    language: str = "en"
    category: str = "premade"
    description: str | None = None
    labels: dict[str, str] = field(default_factory=dict)


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelDefinition] = {}
        self._model_aliases: dict[str, str] = {}
        self._voices: dict[str, VoiceDefinition] = {}
        self._voice_aliases: dict[str, str] = {}

    def register_model(self, model: ModelDefinition) -> None:
        identifiers = {model.id, *model.aliases}
        duplicates = identifiers & (self._models.keys() | self._model_aliases.keys())
        if duplicates:
            raise ValueError(f"Duplicate model identifiers: {sorted(duplicates)}")

        self._models[model.id] = model
        for alias in model.aliases:
            self._model_aliases[alias] = model.id

    def register_voice(self, voice: VoiceDefinition) -> None:
        identifiers = {voice.id, *voice.aliases}
        duplicates = identifiers & (self._voices.keys() | self._voice_aliases.keys())
        if duplicates:
            raise ValueError(f"Duplicate voice identifiers: {sorted(duplicates)}")

        unknown_models = voice.model_ids - self._models.keys()
        if unknown_models:
            raise ValueError(
                f"Voice {voice.id} references unknown models: {sorted(unknown_models)}"
            )

        self._voices[voice.id] = voice
        for alias in voice.aliases:
            self._voice_aliases[alias] = voice.id

    def resolve_model(
        self,
        model_id: str,
        capability: str | None = None,
    ) -> ModelDefinition:
        canonical_id = self._model_aliases.get(model_id, model_id)
        model = self._models.get(canonical_id)
        if model is None:
            raise ModelNotFoundError(f"Model not found: {model_id}")
        if capability and not model.supports(capability):
            raise ModelCapabilityError(
                f"Model {model_id} does not support {capability}."
            )
        return model

    def resolve_voice(
        self,
        voice_id: str,
        model_id: str | None = None,
    ) -> VoiceDefinition:
        canonical_id = self._voice_aliases.get(voice_id, voice_id)
        voice = self._voices.get(canonical_id)
        if voice is None:
            raise VoiceNotFoundError(f"Voice not found: {voice_id}")

        if model_id:
            model = self.resolve_model(model_id, TEXT_TO_SPEECH)
            if model.id not in voice.model_ids:
                raise VoiceNotFoundError(
                    f"Voice {voice_id} is not available for model {model_id}."
                )
        return voice

    def list_models(
        self,
        capability: str | None = None,
    ) -> list[ModelDefinition]:
        models = self._models.values()
        if capability:
            models = (model for model in models if model.supports(capability))
        return sorted(models, key=lambda model: model.id)

    def has_model(self, model_id: str) -> bool:
        return model_id in self._models

    def list_voices(self, model_id: str | None = None) -> list[VoiceDefinition]:
        voices: Iterable[VoiceDefinition] = self._voices.values()
        if model_id:
            model = self.resolve_model(model_id, TEXT_TO_SPEECH)
            voices = (voice for voice in voices if model.id in voice.model_ids)
        return sorted(voices, key=lambda voice: voice.name.lower())


def build_default_registry(
    enabled_model_ids: set[str] | None = None,
) -> ModelRegistry:
    registry = ModelRegistry()
    models = [
        ModelDefinition(
            id="local-tts",
            name="Kokoro local text-to-speech",
            description="Local Kokoro text-to-speech model.",
            provider="kokoro",
            capabilities=frozenset({TEXT_TO_SPEECH}),
            aliases=frozenset(
                {
                    "tts-1",
                    "tts-1-hd",
                    "gpt-4o-mini-tts",
                    "eleven_multilingual_v2",
                    "eleven_turbo_v2_5",
                    "eleven_flash_v2_5",
                }
            ),
            metadata={"local": True},
        ),
        ModelDefinition(
            id="local-stt",
            name="Local speech-to-text router",
            description="Local STT engine router with configured fallbacks.",
            provider="local-stt-router",
            capabilities=frozenset({SPEECH_TO_TEXT}),
            aliases=frozenset(
                {
                    "whisper-1",
                    "gpt-4o-mini-transcribe",
                    "gpt-4o-transcribe",
                }
            ),
            metadata={"local": True},
        ),
    ]

    for model in models:
        if enabled_model_ids is None or model.id in enabled_model_ids:
            registry.register_model(model)

    voices = [
        VoiceDefinition(
            id="af_heart",
            name="Heart",
            provider="kokoro",
            model_ids=frozenset({"local-tts"}),
            aliases=frozenset({"alloy", "sage", "marin"}),
            labels={"gender": "female"},
        ),
        VoiceDefinition(
            id="af_bella",
            name="Bella",
            provider="kokoro",
            model_ids=frozenset({"local-tts"}),
            aliases=frozenset({"ballad", "fable", "shimmer"}),
            labels={"gender": "female"},
        ),
        VoiceDefinition(
            id="af_sarah",
            name="Sarah",
            provider="kokoro",
            model_ids=frozenset({"local-tts"}),
            aliases=frozenset({"coral", "nova"}),
            labels={"gender": "female"},
        ),
        VoiceDefinition(
            id="am_adam",
            name="Adam",
            provider="kokoro",
            model_ids=frozenset({"local-tts"}),
            aliases=frozenset({"ash", "onyx"}),
            labels={"gender": "male"},
        ),
        VoiceDefinition(
            id="am_michael",
            name="Michael",
            provider="kokoro",
            model_ids=frozenset({"local-tts"}),
            aliases=frozenset({"echo", "verse", "cedar"}),
            labels={"gender": "male"},
        ),
    ]
    for voice in voices:
        if all(registry.has_model(model_id) for model_id in voice.model_ids):
            registry.register_voice(voice)

    return registry
