import logging

logger = logging.getLogger(__name__)


def check_database() -> dict:
    """FastAPI mode is stateless; no database health check is needed."""
    return {"status": "skipped", "detail": "Stateless FastAPI mode"}


def check_llm_api() -> dict:
    """Check that the active primary model's API key is configured."""
    from .providers import MODEL_PROFILES
    from .runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_spec = runtime.llm_model_primary
    primary_model = MODEL_PROFILES.get(primary_spec, primary_spec)

    if primary_model.startswith("gpt-oss"):
        key = runtime.cerebras_api_key
        provider = "Cerebras"
    else:
        key = runtime.langextract_api_key
        provider = "Gemini"

    if key and len(key) > 10:
        return {"status": "ok", "model": primary_model, "provider": provider}
    return {"status": "error", "detail": f"{provider} API key not configured", "model": primary_model}
