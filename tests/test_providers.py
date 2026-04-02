import unittest

from extractor.integrations.providers import resolve_model_target


class ProviderRoutingTests(unittest.TestCase):
    def test_ollama_llama_with_tag_routes_to_ollama(self) -> None:
        target = resolve_model_target("llama3.2:latest")
        self.assertEqual(target.provider, "ollama")
        self.assertEqual(target.model_id, "llama3.2:latest")

    def test_plain_llama_name_routes_to_cerebras(self) -> None:
        target = resolve_model_target("llama3.1-8b")
        self.assertEqual(target.provider, "cerebras")
        self.assertEqual(target.model_id, "llama3.1-8b")


if __name__ == "__main__":
    unittest.main()
