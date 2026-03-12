def _check_llm_api() -> dict:
    """Check that the active primary model's API key is configured."""
    from .providers import resolve_model_target
    from .runtime import get_runtime_settings

    runtime = get_runtime_settings()
    target = resolve_model_target(runtime.llm_model_primary)

    if target.provider == "cerebras":
        key = runtime.cerebras_api_key
        provider = "Cerebras"
        ok = bool(key and len(key) > 10)
        detail = f"{provider} API key not configured"
    elif target.provider == "gemini":
        key = runtime.langextract_api_key
        provider = "Gemini"
        ok = bool(key and len(key) > 10)
        detail = f"{provider} API key not configured"
    elif target.provider == "openai":
        key = runtime.openai_api_key
        provider = "OpenAI"
        ok = bool(key and len(key) > 10)
        detail = f"{provider} API key not configured"
    else:
        provider = "Ollama"
        ok = bool(runtime.ollama_base_url)
        detail = "Ollama base URL not configured"

    if ok:
        return {"status": "ok", "model": target.model_id, "provider": provider}
    return {"status": "error", "detail": detail, "model": target.model_id, "provider": provider}


def get_health_status() -> dict:
    """Return overall service health for the stateless FastAPI runtime."""
    llm_api = _check_llm_api()
    return {
        "status": "ok" if llm_api["status"] == "ok" else "degraded",
        "database": {"status": "skipped", "detail": "Stateless FastAPI mode"},
        "llm_api": llm_api,
    }
