"""Model routing and provider-specific extraction backends."""

import concurrent.futures
import json
import logging
import time

import langextract as lx
from langextract import factory as lx_factory

from .postprocess import _repair_json
from .prompts import (
    EXAMPLES,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_GPT_OSS,
    _CEREBRAS_RESPONSE_FORMAT,
)
from .runtime import get_runtime_settings

logger = logging.getLogger(__name__)


MODEL_PROFILES: dict[str, str] = {
    "cerebras": "gpt-oss-120b",
    "gemini": "gemini-2.5-flash",
}

_cerebras_client = None


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


def resolve_model_id(model_spec: str | None) -> str:
    """
    Resolve a model spec to a concrete model ID.
    """
    if not model_spec:
        primary = get_runtime_settings().llm_model_primary
        return MODEL_PROFILES.get(primary, primary)
    return MODEL_PROFILES.get(model_spec, model_spec)


def _build_lx_config(model_id: str) -> lx_factory.ModelConfig:
    """
    Build a LangExtract ModelConfig for Cerebras or Gemini.
    """
    runtime = get_runtime_settings()
    if model_id.startswith("gpt-oss"):
        return lx_factory.ModelConfig(
            model_id=model_id,
            provider_kwargs={
                "base_url": runtime.cerebras_base_url,
                "api_key": runtime.cerebras_api_key or None,
                "max_workers": runtime.llm_max_workers_cerebras,
            },
        )

    return lx_factory.ModelConfig(
        model_id=model_id,
        provider_kwargs={
            "api_key": runtime.langextract_api_key or None,
            "max_workers": runtime.llm_max_workers_gemini,
        },
    )


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

    def _call_chunk(idx_chunk: tuple[int, str]) -> tuple[int, str, dict[str, int]]:
        idx, chunk = idx_chunk
        labelled = f"=== INVOICE ITEMS — SECTION {idx + 1} OF {len(chunks)} ===\n{chunk}"
        user_content = f"{header_context}\n\n{labelled}" if header_context else labelled
        for attempt in range(max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": EXTRACTION_PROMPT_GPT_OSS},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0,
                    response_format=_CEREBRAS_RESPONSE_FORMAT,
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
            for candidate in (raw, _repair_json(raw)):
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
    model_id: str,
    header_context: str = "",
) -> tuple[str, object, dict[str, int]]:
    """
    Run extraction and return (json_str, annotated_doc).
    """
    if model_id.startswith("gpt-oss"):
        return extract_cerebras_direct(context_text, model_id, header_context)

    config = _build_lx_config(model_id)
    prompt = EXTRACTION_PROMPT
    buffer = get_runtime_settings().llm_max_char_buffer

    try:
        annotated_doc = lx.extract(
            text_or_documents=context_text,
            prompt_description=prompt,
            examples=EXAMPLES,
            config=config,
            additional_context=header_context or None,
            max_char_buffer=buffer,
        )
    except Exception as exc:
        logger.warning(
            "lx.extract() failed (%s: %s) — returning empty result",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return "[]", None, {}

    all_items = []
    for extraction in annotated_doc.extractions:
        item = {"description": extraction.extraction_text}
        if extraction.attributes:
            item.update(extraction.attributes)
        all_items.append(item)

    logger.debug(
        "[raw_output] model=%s  extracted=%d items  preview=%s",
        model_id,
        len(all_items),
        json.dumps(all_items[:3], ensure_ascii=False)[:500],
    )

    return json.dumps(all_items, ensure_ascii=False), annotated_doc, {}
