import unittest

from app.model_registry import (
    ModelDefinition,
    ModelCapabilityError,
    ModelNotFoundError,
    ModelRegistry,
    SPEECH_TO_TEXT,
    TEXT_TO_SPEECH,
    VoiceDefinition,
    build_default_registry,
)
from app.services.tts_service import TTSService


class ModelRegistryTests(unittest.TestCase):
    def test_resolves_public_aliases_to_local_models(self):
        registry = build_default_registry()

        self.assertEqual(
            registry.resolve_model("gpt-4o-mini-tts", TEXT_TO_SPEECH).id,
            "local-tts",
        )
        self.assertEqual(
            registry.resolve_model("eleven_multilingual_v2", TEXT_TO_SPEECH).id,
            "local-tts",
        )
        self.assertEqual(
            registry.resolve_model("whisper-1", SPEECH_TO_TEXT).id,
            "local-stt",
        )

    def test_rejects_capability_mismatch(self):
        registry = build_default_registry()

        with self.assertRaises(ModelCapabilityError):
            registry.resolve_model("local-stt", TEXT_TO_SPEECH)

    def test_enabled_models_can_remove_a_model_and_its_aliases(self):
        registry = build_default_registry({"local-tts"})

        self.assertEqual(
            [model.id for model in registry.list_models()],
            ["local-tts"],
        )
        with self.assertRaises(ModelNotFoundError):
            registry.resolve_model("whisper-1")

    def test_resolves_openai_voice_aliases(self):
        registry = build_default_registry()

        self.assertEqual(
            registry.resolve_voice("alloy", "local-tts").id,
            "af_heart",
        )

    def test_service_dispatches_a_catalog_model_to_registered_backend(self):
        registry = ModelRegistry()
        registry.register_model(
            ModelDefinition(
                id="custom-tts",
                provider="custom",
                capabilities=frozenset({TEXT_TO_SPEECH}),
            )
        )
        registry.register_voice(
            VoiceDefinition(
                id="custom-voice",
                name="Custom",
                provider="custom",
                model_ids=frozenset({"custom-tts"}),
            )
        )

        class Backend:
            def stream_pcm(self, **kwargs):
                yield f"{kwargs['voice']}:{kwargs['text']}".encode()

        service = TTSService(registry)
        service.register_backend("custom", Backend())

        self.assertEqual(
            b"".join(
                service.stream_pcm(
                    "hello",
                    voice="custom-voice",
                    model="custom-tts",
                )
            ),
            b"custom-voice:hello",
        )


if __name__ == "__main__":
    unittest.main()
