import unittest
import json

from extractor.runtime import get_runtime_settings
from extractor.providers import list_model_families, resolve_model_target
from extractor.llm.vllm import VLLMProvider
from extractor.llm.vlm import VLMProvider
from unittest.mock import patch


class ProviderRoutingTests(unittest.TestCase):
    def test_ollama_llama_with_tag_routes_to_ollama(self) -> None:
        target = resolve_model_target("llama3.2:latest")
        self.assertEqual(target.provider, "ollama")
        self.assertEqual(target.model_id, "llama3.2:latest")

    def test_plain_llama_name_routes_to_cerebras(self) -> None:
        target = resolve_model_target("llama3.1-8b")
        self.assertEqual(target.provider, "cerebras")
        self.assertEqual(target.model_id, "llama3.1-8b")

    def test_explicit_vllm_model_spec_is_supported(self) -> None:
        target = resolve_model_target("vllm::Qwen/Qwen2.5-14B-Instruct")
        self.assertEqual(target.provider, "vllm")
        self.assertEqual(target.model_id, "Qwen/Qwen2.5-14B-Instruct")

    def test_explicit_vlm_model_spec_is_supported(self) -> None:
        target = resolve_model_target("vlm::Qwen/Qwen2.5-VL-7B-Instruct")
        self.assertEqual(target.provider, "vlm")
        self.assertEqual(target.model_id, "Qwen/Qwen2.5-VL-7B-Instruct")

    @patch.dict(
        "os.environ",
        {
            "VLLM_BASE_URL": "http://127.0.0.1:7401/v1",
            "VLLM_MODELS": "Qwen/Qwen2.5-14B-Instruct|Qwen/Qwen2.5-7B-Instruct",
            "VLM_BASE_URL": "http://127.0.0.1:7402/v1",
            "VLM_MODELS": "Qwen/Qwen2.5-VL-7B-Instruct",
        },
        clear=False,
    )
    def test_vllm_and_vlm_families_appear_in_model_catalog(self) -> None:
        get_runtime_settings.cache_clear()
        try:
            families = {family["provider"]: family for family in list_model_families()}
        finally:
            get_runtime_settings.cache_clear()

        self.assertIn("vllm", families)
        self.assertEqual(
            [model["model_id"] for model in families["vllm"]["models"]],
            [
                "Qwen/Qwen2.5-14B-Instruct",
                "Qwen/Qwen2.5-7B-Instruct",
            ],
        )
        self.assertIn("vlm", families)
        self.assertEqual(
            [model["model_id"] for model in families["vlm"]["models"]],
            ["Qwen/Qwen2.5-VL-7B-Instruct"],
        )

    def test_vllm_provider_sets_json_mode(self) -> None:
        captured: dict[str, object] = {}

        def fake_request(request, **kwargs):
            captured["payload"] = json.loads(request.data.decode())
            return {"choices": [{"message": {"content": '{"items":[]}'}}]}

        provider = VLLMProvider(
            api_key="token",
            base_url="http://127.0.0.1:7401/v1",
        )

        with patch.object(VLLMProvider, "_request_json", side_effect=fake_request):
            result = provider.generate("system", "user", "vllm::Qwen/Qwen2.5-14B-Instruct")

        payload = captured["payload"]
        self.assertEqual(result, '{"items":[]}')
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["temperature"], 0)

    def test_vlm_provider_builds_multimodal_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_request(request, **kwargs):
            captured["payload"] = json.loads(request.data.decode())
            return {"choices": [{"message": {"content": '{"items":[]}'}}]}

        provider = VLMProvider(
            api_key="token",
            base_url="http://127.0.0.1:7402/v1",
        )

        with patch.object(VLMProvider, "_request_json", side_effect=fake_request):
            result = provider.generate_from_images(
                "system",
                "extract",
                ["data:image/png;base64,abc", "file:///tmp/page-2.png"],
                "vlm::Qwen/Qwen2.5-VL-7B-Instruct",
            )

        payload = captured["payload"]
        self.assertEqual(result, '{"items":[]}')
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["messages"][1]["content"][0], {"type": "text", "text": "extract"})
        self.assertEqual(payload["messages"][1]["content"][1]["image_url"]["url"], "data:image/png;base64,abc")
        self.assertEqual(payload["messages"][1]["content"][2]["image_url"]["url"], "file:///tmp/page-2.png")


if __name__ == "__main__":
    unittest.main()
