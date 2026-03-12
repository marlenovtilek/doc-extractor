from types import SimpleNamespace
import unittest

from extractor.providers import (
    _extract_cerebras_usage,
    _is_non_retryable_cerebras_error,
    _is_retryable_cerebras_error,
)


class CerebrasRetryPolicyTests(unittest.TestCase):
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
