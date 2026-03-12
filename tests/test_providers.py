import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extractor.providers import (
    _extract_cerebras_usage,
    _is_non_retryable_cerebras_error,
    _is_retryable_cerebras_error,
    _build_lx_config,
    resolve_model_target,
)
from extractor.runtime import clear_runtime_settings_cache


class CerebrasRetryPolicyTests(unittest.TestCase):
    def tearDown(self):
        clear_runtime_settings_cache()

    def test_extract_cerebras_usage_reads_usage_fields(self):
        resp = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=123,
                completion_tokens=45,
                total_tokens=168,
                prompt_tokens_details=SimpleNamespace(cached_tokens=12),
            )
        )

        self.assertEqual(
            _extract_cerebras_usage(resp),
            {
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "total_tokens": 168,
                "cached_prompt_tokens": 12,
            },
        )

    def test_queue_exceeded_is_retryable(self):
        exc = Exception(
            "Error code: 429 - {'message': \"We're experiencing high traffic right now!\", "
            "'code': 'queue_exceeded'}"
        )

        self.assertTrue(_is_retryable_cerebras_error(exc))
        self.assertFalse(_is_non_retryable_cerebras_error(exc))

    def test_token_quota_exceeded_is_not_retryable(self):
        exc = Exception(
            "Error code: 429 - {'message': 'Tokens per day limit exceeded - too many tokens processed.', "
            "'type': 'too_many_tokens_error', 'param': 'quota', 'code': 'token_quota_exceeded'}"
        )

        self.assertFalse(_is_retryable_cerebras_error(exc))
        self.assertTrue(_is_non_retryable_cerebras_error(exc))

    @patch.dict(
        os.environ,
        {
            "OPENAI_MODEL_DEFAULT": "gpt-4o",
            "OLLAMA_MODEL_DEFAULT": "qwen2.5:14b",
        },
        clear=False,
    )
    def test_resolve_model_target_supports_aliases_and_explicit_provider_syntax(self):
        clear_runtime_settings_cache()

        openai_target = resolve_model_target("openai")
        ollama_target = resolve_model_target("ollama")
        explicit_ollama_target = resolve_model_target("ollama::mistral:7b")

        self.assertEqual((openai_target.provider, openai_target.model_id), ("openai", "gpt-4o"))
        self.assertEqual((ollama_target.provider, ollama_target.model_id), ("ollama", "qwen2.5:14b"))
        self.assertEqual(
            (explicit_ollama_target.provider, explicit_ollama_target.model_id),
            ("ollama", "mistral:7b"),
        )

    def test_resolve_model_target_infers_provider_from_raw_model(self):
        self.assertEqual(resolve_model_target("gpt-4o-mini").provider, "openai")
        self.assertEqual(resolve_model_target("gemini-2.5-flash").provider, "gemini")
        self.assertEqual(resolve_model_target("qwen2.5:7b").provider, "ollama")
        self.assertEqual(resolve_model_target("gpt-oss-120b").provider, "cerebras")

    @patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "sk-openai-test",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_TIMEOUT_S": "180",
        },
        clear=False,
    )
    def test_build_lx_config_supports_openai_and_ollama(self):
        clear_runtime_settings_cache()

        openai_config = _build_lx_config(resolve_model_target("openai::gpt-4o-mini"))
        ollama_config = _build_lx_config(resolve_model_target("ollama::qwen2.5:7b"))

        self.assertEqual(openai_config.provider, "openai")
        self.assertEqual(openai_config.model_id, "gpt-4o-mini")
        self.assertEqual(openai_config.provider_kwargs["api_key"], "sk-openai-test")
        self.assertEqual(openai_config.provider_kwargs["base_url"], "https://api.openai.com/v1")

        self.assertEqual(ollama_config.provider, "ollama")
        self.assertEqual(ollama_config.model_id, "qwen2.5:7b")
        self.assertEqual(ollama_config.provider_kwargs["base_url"], "http://localhost:11434")
        self.assertEqual(ollama_config.provider_kwargs["timeout"], 180)
