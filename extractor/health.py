from extractor.runtime import get_runtime_settings
from extractor.providers import get_provider_statuses, resolve_model_target


def get_health_status() -> dict:
    """Return overall service health and provider readiness."""
    runtime = get_runtime_settings()
    provider_statuses = get_provider_statuses()
    try:
        active_target = resolve_model_target(runtime.llm_model_primary)
        active_provider = provider_statuses[active_target.provider]

        llm_api = {
            "status": "ok" if active_provider["configured"] else "error",
            "provider": active_provider["label"],
            "model": active_target.model_id,
        }
        if not active_provider["configured"]:
            llm_api["detail"] = active_provider["detail"]
    except (KeyError, ValueError) as exc:
        llm_api = {
            "status": "error",
            "provider": "unknown",
            "model": runtime.llm_model_primary,
            "detail": str(exc),
        }

    return {
        "status": "ok" if llm_api["status"] == "ok" else "degraded",
        "database": {"status": "skipped", "detail": "Stateless FastAPI mode"},
        "llm_api": llm_api,
        "providers": provider_statuses,
    }
