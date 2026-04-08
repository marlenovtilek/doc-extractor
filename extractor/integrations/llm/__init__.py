import logging

from extractor.config.runtime import get_runtime_settings
from .gemini import GeminiProvider
from .cerebras import CerebrasProvider
from .openai import OpenAIProvider
from .ollama import OllamaProvider
from .vllm import VLLMProvider

logger = logging.getLogger(__name__)

def get_llm_provider(provider_name: str):
    runtime = get_runtime_settings()
    
    # Реестр провайдеров
    providers = {
        "gemini": lambda: GeminiProvider(
            api_key=runtime.gemini_api_key,
            default_timeout_s=runtime.gemini_timeout_s,
        ),
        "cerebras": lambda: CerebrasProvider(
            api_key=runtime.cerebras_api_key,
            base_url=runtime.cerebras_base_url,
            default_timeout_s=runtime.cerebras_timeout_s,
        ),
        "openai": lambda: OpenAIProvider(
            api_key=runtime.openai_api_key,
            default_timeout_s=runtime.openai_timeout_s,
        ),
        "ollama": lambda: OllamaProvider(
            base_url=runtime.ollama_base_url,
            default_timeout_s=runtime.ollama_timeout_s,
        ),
        "vllm": lambda: VLLMProvider(
            api_key=runtime.vllm_api_key,
            base_url=runtime.vllm_base_url,
            default_timeout_s=runtime.vllm_timeout_s,
            supports_large_context=runtime.vllm_supports_large_context,
        ),
    }
    
    if provider_name not in providers:
        raise ValueError(f"Unsupported provider '{provider_name}'.")
    
    return providers[provider_name]()
