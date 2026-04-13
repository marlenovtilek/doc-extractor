from dataclasses import dataclass
from typing import Any
from ..config.runtime import get_runtime_settings

_SUPPORTED_PROVIDERS = ("gemini", "openai", "vllm", "vlm", "ollama", "cerebras")

def _provider_display_name(provider: str) -> str:
    """Преобразует технический ID провайдера в красивое имя для UI."""
    names = {
        "cerebras": "Cerebras (Llama-3)",
        "gemini": "Google Gemini",
        "openai": "OpenAI (GPT)",
        "vllm": "vLLM (Self-hosted)",
        "vlm": "VLM (PDF/Image via vLLM)",
        "ollama": "Ollama (Local)",
    }
    return names.get(provider.lower(), provider.title())

@dataclass(frozen=True)
class ModelTarget:
    provider: str
    model_id: str


def build_model_spec(provider: str, model_id: str) -> str:
    return f"{provider}::{model_id}"


def _provider_models(provider: str) -> tuple[str, ...]:
    rt = get_runtime_settings()
    mapping = {
        "gemini": rt.gemini_models,
        "openai": rt.gpt_models,
        "ollama": rt.ollama_models,
        "cerebras": rt.cerebras_models,
        "vllm": rt.vllm_models,
        "vlm": rt.vlm_models,
    }
    return mapping.get(provider, ())


def _infer_provider_from_raw_model(model_id: str) -> str | None:
    raw = model_id.strip().lower()
    if not raw:
        return None
    if ":" in raw:
        return "ollama"
    if raw.startswith("gpt-"):
        return "openai"
    if raw.startswith("gemini-"):
        return "gemini"
    if raw.startswith("llama"):
        return "cerebras"
    return None


def _resolve_provider_default(provider: str) -> ModelTarget:
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider '{provider}'.")
    models = _provider_models(provider)
    if not models:
        raise ValueError(f"No models configured for provider '{provider}'.")
    return ModelTarget(provider=provider, model_id=models[0])


def resolve_model_target(model_spec: str | None) -> ModelTarget:
    rt = get_runtime_settings()
    raw = (model_spec or rt.llm_model_primary or "gemini").strip()

    if "::" in raw:
        p, m = raw.split("::", 1)
        provider = p.strip().lower()
        model_id = m.strip()
        if provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        if not model_id:
            raise ValueError(f"Empty model id in model spec '{raw}'.")
        return ModelTarget(provider=provider, model_id=model_id)

    if raw in _SUPPORTED_PROVIDERS:
        return _resolve_provider_default(raw)

    inferred_provider = _infer_provider_from_raw_model(raw)
    if inferred_provider is not None:
        return ModelTarget(provider=inferred_provider, model_id=raw)

    raise ValueError(f"Unsupported model spec '{raw}'.")

def ensure_model_spec_ready(model_spec: str | None) -> ModelTarget:
    """Проверяет, разрешается ли спецификация модели (нужна для extraction.py)."""
    return resolve_model_target(model_spec)

def list_model_families() -> list[dict[str, Any]]:
    """Формирует сгруппированный список моделей для динамического Web UI."""
    statuses = get_provider_statuses()

    families: list[dict[str, Any]] = []
    for provider in _SUPPORTED_PROVIDERS:
        families.append({
            "provider": provider,
            "label": statuses.get(provider, {}).get("label", _provider_display_name(provider)),
            "configured": statuses.get(provider, {}).get("configured", False),
            "models": [
                {
                    "label": model_id,
                    "value": build_model_spec(provider, model_id),
                    "model_id": model_id,
                }
                for model_id in _provider_models(provider)
            ],
        })
    return families

def get_provider_statuses() -> dict[str, dict[str, Any]]:
    rt = get_runtime_settings()
    return {
        "gemini": {
            "configured": bool(rt.gemini_api_key),
            "label": _provider_display_name("gemini"),
            "detail": "" if rt.gemini_api_key else "Set GEMINI_API_KEY to enable Gemini requests.",
        },
        "cerebras": {
            "configured": bool(rt.cerebras_api_key),
            "label": _provider_display_name("cerebras"),
            "detail": "" if rt.cerebras_api_key else "Set CEREBRAS_API_KEY to enable Cerebras requests.",
        },
        "openai": {
            "configured": bool(rt.openai_api_key),
            "label": _provider_display_name("openai"),
            "detail": "" if rt.openai_api_key else "Set OPENAI_API_KEY to enable OpenAI requests.",
        },
        "vllm": {
            "configured": bool(rt.vllm_base_url),
            "label": _provider_display_name("vllm"),
            "detail": "" if rt.vllm_base_url else "Set VLLM_BASE_URL to your self-hosted vLLM endpoint.",
        },
        "vlm": {
            "configured": bool(rt.vlm_base_url),
            "label": _provider_display_name("vlm"),
            "detail": "" if rt.vlm_base_url else "Set VLM_BASE_URL to your self-hosted multimodal vLLM endpoint.",
        },
        "ollama": {
            "configured": bool(rt.ollama_base_url),
            "label": _provider_display_name("ollama"),
            "detail": "" if rt.ollama_base_url else "Set OLLAMA_BASE_URL to reach a local Ollama server.",
        },
    }
