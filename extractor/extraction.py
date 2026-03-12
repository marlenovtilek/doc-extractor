"""Compatibility facade for the invoice extraction pipeline."""

from .pipeline import run_invoice_extraction
from .postprocess import (
    _repair_json,
    deduplicate_items,
    post_fill_from_header,
    spread_single_country_origin,
    validate_and_parse,
)
from .preprocess import clean_text, extract_header, parse_full_doc_metadata, parse_header_metadata
from .prompts import (
    EXAMPLES,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_GPT_OSS,
    _CEREBRAS_RESPONSE_FORMAT,
    _HEADER_FIELDS,
)
from .providers import (
    MODEL_PROFILES,
    _build_lx_config,
    _get_cerebras_client,
    _split_text_into_chunks,
    extract_cerebras_direct,
    extract_with_langextract_optimized,
    resolve_model_id,
)

__all__ = [
    "EXAMPLES",
    "EXTRACTION_PROMPT",
    "EXTRACTION_PROMPT_GPT_OSS",
    "MODEL_PROFILES",
    "_CEREBRAS_RESPONSE_FORMAT",
    "_HEADER_FIELDS",
    "_build_lx_config",
    "_get_cerebras_client",
    "_repair_json",
    "_split_text_into_chunks",
    "clean_text",
    "deduplicate_items",
    "extract_cerebras_direct",
    "extract_header",
    "extract_with_langextract_optimized",
    "parse_full_doc_metadata",
    "parse_header_metadata",
    "post_fill_from_header",
    "resolve_model_id",
    "run_invoice_extraction",
    "spread_single_country_origin",
    "validate_and_parse",
]
