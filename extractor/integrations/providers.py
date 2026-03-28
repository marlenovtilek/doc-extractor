"""Model routing and provider-specific extraction backends."""

import concurrent.futures
from dataclasses import dataclass
import json
import logging
import os
import re
import time

import langextract as lx
from langextract import factory as lx_factory
from langextract.providers import patterns as lx_patterns

from ..config.runtime import get_runtime_settings
from ..documents.invoice.invoice_llm import (
    EXAMPLES as INVOICE_EXAMPLES,
    EXTRACTION_PROMPT as INVOICE_EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_GPT_OSS as INVOICE_EXTRACTION_PROMPT_GPT_OSS,
    _CEREBRAS_RESPONSE_FORMAT as INVOICE_CEREBRAS_RESPONSE_FORMAT,
    _repair_json as repair_invoice_json,
)

logger = logging.getLogger(__name__)

_cerebras_client = None
_SUPPORTED_PROVIDERS = {"cerebras", "gemini", "openai", "ollama"}


@dataclass(frozen=True)
class ModelTarget:
    provider: str
    model_id: str

def _invoice_prompt_bundle() -> tuple[str, str, list, dict]:
    return (
        INVOICE_EXTRACTION_PROMPT,
        INVOICE_EXTRACTION_PROMPT_GPT_OSS,
        INVOICE_EXAMPLES,
        INVOICE_CEREBRAS_RESPONSE_FORMAT,
    )


def _repair_invoice_json(raw_text: str) -> str:
    return repair_invoice_json(raw_text)


def _provider_display_name(provider: str) -> str:
    names = {
        "cerebras": "Cerebras",
        "gemini": "Gemini",
        "openai": "OpenAI",
        "ollama": "Ollama",
    }
    return names.get(provider, provider.title())


def _provider_default_targets() -> dict[str, ModelTarget]:
    runtime = get_runtime_settings()
    cerebras_model = os.getenv("CEREBRAS_MODEL", "llama3.1-8b") 
    
    return {
        "cerebras": ModelTarget(provider="cerebras", model_id=cerebras_model),
        "gemini": ModelTarget(provider="gemini", model_id="gemini-2.5-flash"),
        "openai": ModelTarget(provider="openai", model_id=runtime.openai_model_default),
        "ollama": ModelTarget(provider="ollama", model_id=runtime.ollama_model_default),
    }

def _alias_model_targets() -> dict[str, ModelTarget]:
    runtime = get_runtime_settings()
    cerebras_model = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
    return {
        "cerebras": ModelTarget(provider="cerebras", model_id=cerebras_model),
        "gemini": ModelTarget(provider="gemini", model_id="gemini-2.5-flash"),
        "gemini-flash": ModelTarget(provider="gemini", model_id="gemini-2.5-flash"),
        "gemini-pro": ModelTarget(provider="gemini", model_id="gemini-2.5-pro"),
        "openai": ModelTarget(provider="openai", model_id=runtime.openai_model_default),
        "ollama": ModelTarget(provider="ollama", model_id=runtime.ollama_model_default),
    }


def _visible_model_aliases() -> tuple[str, ...]:
    return ("cerebras", "gemini-flash", "gemini-pro", "openai", "ollama")


def get_provider_statuses() -> dict[str, dict[str, object]]:
    """
    Return configuration-level readiness for each supported provider.

    This is intentionally a config check, not a live connectivity probe.
    """
    runtime = get_runtime_settings()
    statuses: dict[str, dict[str, object]] = {}

    for provider, target in _provider_default_targets().items():
        if provider == "cerebras":
            configured = bool(runtime.cerebras_api_key and len(runtime.cerebras_api_key) > 10)
            detail = "" if configured else "Set CEREBRAS_API_KEY in .env"
            kind = "hosted"
        elif provider == "gemini":
            configured = bool(runtime.langextract_api_key and len(runtime.langextract_api_key) > 10)
            detail = "" if configured else "Set LANGEXTRACT_API_KEY in .env"
            kind = "hosted"
        elif provider == "openai":
            configured = bool(runtime.openai_api_key and len(runtime.openai_api_key) > 10)
            detail = "" if configured else "Set OPENAI_API_KEY in .env"
            kind = "hosted"
        else:
            configured = bool(runtime.ollama_base_url)
            detail = "" if configured else "Set OLLAMA_BASE_URL in .env"
            kind = "local"

        statuses[provider] = {
            "provider": provider,
            "label": _provider_display_name(provider),
            "configured": configured,
            "status": "ready" if configured else "missing_config",
            "detail": detail,
            "kind": kind,
            "default_model_id": target.model_id,
        }

    return statuses


def list_model_profiles() -> list[dict[str, object]]:
    """Return model aliases enriched with provider readiness metadata."""
    statuses = get_provider_statuses()
    profiles: list[dict[str, object]] = []
    alias_targets = _alias_model_targets()
    for alias in _visible_model_aliases():
        target = alias_targets[alias]
        provider_status = statuses[target.provider]
        profiles.append(
            {
                "alias": alias,
                "provider": target.provider,
                "provider_label": provider_status["label"],
                "model_id": target.model_id,
                "configured": provider_status["configured"],
                "status": provider_status["status"],
                "detail": provider_status["detail"],
                "kind": provider_status["kind"],
            }
        )
    return profiles


def list_model_families() -> list[dict[str, object]]:
    """Return grouped model choices for two-step UI selection."""
    statuses = get_provider_statuses()
    profiles = list_model_profiles()
    grouped: dict[str, list[dict[str, object]]] = {provider: [] for provider in _SUPPORTED_PROVIDERS}
    for profile in profiles:
        grouped[profile["provider"]].append(profile)

    ordered_providers = ("cerebras", "gemini", "openai", "ollama")
    families: list[dict[str, object]] = []
    for provider in ordered_providers:
        provider_status = statuses[provider]
        models = grouped.get(provider, [])
        families.append(
            {
                "provider": provider,
                "label": provider_status["label"],
                "configured": provider_status["configured"],
                "status": provider_status["status"],
                "detail": provider_status["detail"],
                "kind": provider_status["kind"],
                "default_model_id": provider_status["default_model_id"],
                "models": models,
            }
        )
    return families


def _extract_cerebras_usage(resp) -> dict[str, int]:
    """Extract token usage counters from a Cerebras SDK response."""
    usage = getattr(resp, "usage", None)
    if not usage:
        return {}

    metrics: dict[str, int] = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, field, None)
        if value is None:
            continue
        try:
            metrics[field] = int(value)
        except (TypeError, ValueError):
            continue

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = getattr(prompt_details, "cached_tokens", None) if prompt_details else None
    if cached_tokens is not None:
        try:
            metrics["cached_prompt_tokens"] = int(cached_tokens)
        except (TypeError, ValueError):
            pass

    return metrics


def _merge_usage_counts(usages: list[dict[str, int]]) -> dict[str, int]:
    """Sum integer token counters across chunks."""
    totals: dict[str, int] = {}
    for usage in usages:
        for key, value in usage.items():
            if not isinstance(value, int):
                continue
            totals[key] = totals.get(key, 0) + value
    return totals


def _get_cerebras_client():
    """Return the process-wide Cerebras client, creating it on first call."""
    global _cerebras_client
    if _cerebras_client is None:
        from cerebras.cloud.sdk import Cerebras

        runtime = get_runtime_settings()
        _cerebras_client = Cerebras(
            base_url=runtime.cerebras_base_url,
            api_key=runtime.cerebras_api_key,
        )
        logger.debug("[cerebras] singleton client created (TCP warming active)")
    return _cerebras_client


def _is_retryable_cerebras_error(exc: Exception) -> bool:
    """Return True for transient Cerebras queue / 429 failures."""
    message = str(exc).lower()
    name = type(exc).__name__
    if _is_non_retryable_cerebras_error(exc):
        return False
    return name == "RateLimitError" or any(
        marker in message
        for marker in ("queue_exceeded", "too_many_requests", "high traffic", "429")
    )


def _is_non_retryable_cerebras_error(exc: Exception) -> bool:
    """Return True for Cerebras quota failures that backoff cannot fix."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "token_quota_exceeded",
            "too_many_tokens_error",
            "tokens per day limit exceeded",
            "daily token limit",
        )
    )


def _matches_any_pattern(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)


def resolve_model_target(model_spec: str | None) -> ModelTarget:
    runtime = get_runtime_settings()
    raw = (model_spec or runtime.llm_model_primary or "").strip()

    if not raw:
        raise ValueError("Model spec is empty.")

    alias_targets = _alias_model_targets()
    if raw in alias_targets:
        return alias_targets[raw]

    if "::" in raw:
        provider, model_id = raw.split("::", 1)
        provider = provider.strip().lower()
        model_id = model_id.strip()

        if provider not in _SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
            raise ValueError(
                f"Unsupported provider '{provider}' in model spec '{raw}'. "
                f"Supported providers: {supported}."
            )

        if not model_id:
            return _provider_default_targets()[provider]

        return ModelTarget(provider=provider, model_id=model_id)

    lowered = raw.lower()
    if lowered.startswith("gpt-oss"):
        return ModelTarget(provider="cerebras", model_id=raw)

    if _matches_any_pattern(lowered, lx_patterns.GEMINI_PATTERNS):
        return ModelTarget(provider="gemini", model_id=raw)

    if _matches_any_pattern(lowered, lx_patterns.OPENAI_PATTERNS):
        return ModelTarget(provider="openai", model_id=raw)

    if _matches_any_pattern(lowered, lx_patterns.OLLAMA_PATTERNS):
        return ModelTarget(provider="ollama", model_id=raw)

    raise ValueError(
        f"Unsupported model spec '{raw}'. Use a known alias or explicit syntax "
        f"'provider::model_id'."
    )


def get_display_model_alias(model_spec: str | None) -> str:
    """Normalize a model spec to the closest UI-visible alias when possible."""
    raw = (model_spec or "").strip()
    if not raw:
        return ""

    try:
        target = resolve_model_target(raw)
    except ValueError:
        return raw

    alias_targets = _alias_model_targets()
    for alias in _visible_model_aliases():
        if alias_targets[alias] == target:
            return alias
    return raw


def get_display_model_family(model_spec: str | None) -> str:
    """Normalize a model spec to the provider family used in the UI."""
    raw = (model_spec or "").strip()
    if not raw:
        return ""
    try:
        return resolve_model_target(raw).provider
    except ValueError:
        return ""


def resolve_model_id(model_spec: str | None) -> str:
    """Resolve a model spec to the concrete model ID only."""
    return resolve_model_target(model_spec).model_id


def ensure_model_target_ready(target: ModelTarget) -> None:
    """Raise ValueError when a provider is selected but not configured."""
    status = get_provider_statuses()[target.provider]
    if status["configured"]:
        return
    label = status["label"]
    detail = status["detail"]
    raise ValueError(f"{label} is not configured. {detail}")


def ensure_model_spec_ready(model_spec: str | None) -> ModelTarget:
    """Resolve and validate a model spec before extraction."""
    target = resolve_model_target(model_spec)
    ensure_model_target_ready(target)
    return target


def _build_lx_config(target: ModelTarget) -> lx_factory.ModelConfig:
    """Build a LangExtract ModelConfig for supported LangExtract providers."""
    runtime = get_runtime_settings()

    if target.provider == "cerebras":
        return lx_factory.ModelConfig(
            model_id=target.model_id,
            provider_kwargs={
                "api_key": runtime.cerebras_api_key or None,
                "base_url": runtime.cerebras_base_url,
            },
        )
    
    if target.provider == "gemini":
        return lx_factory.ModelConfig(
            model_id=target.model_id,
            provider_kwargs={
                "api_key": runtime.langextract_api_key or None,
                "max_workers": runtime.llm_max_workers_gemini,
            },
        )

    if target.provider == "openai":
        return lx_factory.ModelConfig(
            model_id=target.model_id,
            provider_kwargs={
                "api_key": runtime.openai_api_key or None,
                "base_url": runtime.openai_base_url or None,
                "organization": runtime.openai_organization or None,
                "max_workers": runtime.llm_max_workers_openai,
            },
        )

    if target.provider == "ollama":
        return lx_factory.ModelConfig(
            model_id=target.model_id,
            provider_kwargs={
                "base_url": runtime.ollama_base_url,
                "api_key": runtime.ollama_api_key or None,
                "timeout": runtime.ollama_timeout_s,
            },
        )

    raise ValueError(f"LangExtract config is not supported for provider '{target.provider}'.")


def _split_text_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into newline-safe chunks of at most max_chars."""
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def extract_cerebras_direct(
    context_text: str,
    model_id: str,
    header_context: str = "",
) -> tuple[str, None, dict[str, int]]:
    """
    Native Cerebras SDK with parallel chunking — no LangExtract, no resolver.
    """
    runtime = get_runtime_settings()
    buffer = runtime.llm_max_char_buffer_cerebras
    max_workers = runtime.llm_max_workers_cerebras

    chunks = _split_text_into_chunks(context_text, buffer)
    n_workers = min(len(chunks), max_workers)

    logger.debug(
        "[cerebras_direct] model=%s  total_chars=%d  chunks=%d  workers=%d",
        model_id,
        len(context_text),
        len(chunks),
        n_workers,
    )

    client = _get_cerebras_client()
    max_retries = runtime.cerebras_max_retries
    retry_base_delay_s = runtime.cerebras_retry_base_delay_s
    _, extraction_prompt_gpt_oss, _, cerebras_response_format = _invoice_prompt_bundle()

    def _call_chunk(idx_chunk: tuple[int, str]) -> tuple[int, str, dict[str, int]]:
        idx, chunk = idx_chunk
        labelled = f"=== INVOICE ITEMS — SECTION {idx + 1} OF {len(chunks)} ===\n{chunk}"
        user_content = f"{header_context}\n\n{labelled}" if header_context else labelled
        for attempt in range(max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": extraction_prompt_gpt_oss},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0,
                    response_format=cerebras_response_format,
                    max_tokens=32768,
                )
                raw = resp.choices[0].message.content or '{"items":[]}'
                usage = _extract_cerebras_usage(resp)
                if hasattr(resp, "time_info") and resp.time_info:
                    ti = resp.time_info
                    logger.debug(
                        "[cerebras_direct] chunk %d  queue=%.3fs  prompt=%.3fs  completion=%.3fs  total=%.3fs",
                        idx,
                        getattr(ti, "queue_time", 0) or 0,
                        getattr(ti, "prompt_process_time", 0) or 0,
                        getattr(ti, "completion_time", 0) or 0,
                        getattr(ti, "total_time", 0) or 0,
                    )
                if usage:
                    logger.debug(
                        "[cerebras_direct] chunk %d usage  prompt=%d  completion=%d  total=%d",
                        idx,
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        usage.get("total_tokens", 0),
                    )
                return idx, raw, usage
            except Exception as exc:
                should_retry = attempt < max_retries and _is_retryable_cerebras_error(exc)
                if should_retry:
                    delay_s = retry_base_delay_s * (2**attempt)
                    logger.warning(
                        "[cerebras_direct] chunk %d retry %d/%d in %.1fs after %s: %s",
                        idx,
                        attempt + 1,
                        max_retries,
                        delay_s,
                        type(exc).__name__,
                        exc,
                    )
                    time.sleep(delay_s)
                    continue
                if _is_non_retryable_cerebras_error(exc):
                    logger.warning(
                        "[cerebras_direct] chunk %d non-retryable quota failure (%s: %s)",
                        idx,
                        type(exc).__name__,
                        exc,
                    )
                logger.warning(
                    "[cerebras_direct] chunk %d failed (%s: %s)",
                    idx,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                return idx, '{"items":[]}', {}

    all_items: list[dict] = []
    usage_by_chunk: list[dict[str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        for idx, raw, usage in pool.map(_call_chunk, enumerate(chunks)):
            if usage:
                usage_by_chunk.append(usage)
            parsed = None
            for candidate in (raw, _repair_invoice_json(raw)):
                try:
                    parsed = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
            if parsed is None:
                logger.warning("[cerebras_direct] chunk %d: JSON parse failed, skipping", idx)
                continue
            if isinstance(parsed, dict):
                parsed = parsed.get("items", parsed.get("extractions", [parsed]))
            if isinstance(parsed, list):
                all_items.extend(parsed)

    combined = json.dumps(all_items, ensure_ascii=False)
    total_usage = _merge_usage_counts(usage_by_chunk)
    logger.debug(
        "[cerebras_direct] model=%s  chunks=%d  raw_items=%d  preview=%.400s",
        model_id,
        len(chunks),
        len(all_items),
        combined[:400],
    )
    if total_usage:
        logger.debug(
            "[cerebras_direct] model=%s usage  prompt=%d  completion=%d  total=%d",
            model_id,
            total_usage.get("prompt_tokens", 0),
            total_usage.get("completion_tokens", 0),
            total_usage.get("total_tokens", 0),
        )
    return combined, None, total_usage


def extract_with_langextract_optimized(
    context_text: str,
    model: str | ModelTarget,
    header_context: str = "",
) -> tuple[str, object, dict[str, int]]:
    
    # Резолвим модель честно, без принудительного переключения
    target = model if isinstance(model, ModelTarget) else resolve_model_target(model)
    
    # Мы убрали проверку `if target.provider == "cerebras"`
    # Теперь он идет через универсальный LangExtract
    
    extraction_prompt, _, examples, _ = _invoice_prompt_bundle()
    
    # LangExtract автоматически выберет нужный провайдер из _build_lx_config
    extractions, annotated_doc, usage = extract_with_langextract_entities(
        context_text,
        target,
        prompt_description=extraction_prompt,
        examples=examples,
        additional_context=header_context or None,
    )

    all_items = []
    for extraction in extractions:
        item = {"description": extraction["extraction_text"]}
        attributes = extraction.get("attributes", {})
        if isinstance(attributes, dict):
            item.update(attributes)
        all_items.append(item)

    logger.debug(
        "[raw_output] model=%s  extracted=%d items",
        target.model_id,
        len(all_items),
    )

    return json.dumps(all_items, ensure_ascii=False), annotated_doc, usage


def extract_with_langextract_entities(
    context_text: str,
    model: str | ModelTarget,
    *,
    prompt_description: str,
    examples: list,
    additional_context: str | None = None,
    max_char_buffer: int | None = None,
) -> tuple[list[dict[str, object]], object, dict[str, int]]:
    """
    Run LangExtract with document-specific prompts/examples and return raw extractions.

    Each extraction is normalized into:
      {
        "extraction_class": "...",
        "extraction_text": "...",
        "attributes": {...},
      }
    """
    target = model if isinstance(model, ModelTarget) else resolve_model_target(model)

    config = _build_lx_config(target)
    buffer = max_char_buffer or get_runtime_settings().llm_max_char_buffer

    try:
        annotated_doc = lx.extract(
            text_or_documents=context_text,
            prompt_description=prompt_description,
            examples=examples,
            config=config,
            additional_context=additional_context or None,
            max_char_buffer=buffer,
        )
    except Exception as exc:
        logger.error(f"LX Error: {exc}")
        return [], None, {}

    normalized_extractions: list[dict[str, object]] = []
    for extraction in annotated_doc.extractions:
        normalized_extractions.append(
            {
                "extraction_class": extraction.extraction_class,
                "extraction_text": extraction.extraction_text,
                "attributes": dict(extraction.attributes or {}),
            }
        )

    logger.debug(
        "[langextract] model=%s  extracted=%d entities  preview=%s",
        target.model_id,
        len(normalized_extractions),
        json.dumps(normalized_extractions[:5], ensure_ascii=False)[:700],
    )

    return normalized_extractions, annotated_doc, {}
