"""Smart invoice extraction with auto-chunking for 60+ items."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from extractor.integrations.providers import ModelTarget
from extractor.normalizers.currency import load_currency_db
from .invoice_prompt import CHUNK_EXTRACTION_PROMPT
from .invoice_validator import validate_invoice_json, extract_header_fields
from .invoice_simple import _call_gemini, _call_cerebras, _call_ollama
from extractor.config.runtime import get_runtime_settings


def clean_invoice_text(ocr_draft: str) -> str:
    """Simple OCR cleanup."""
    if not ocr_draft:
        return ""
    
    import re
    text = ocr_draft.replace('\r', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    lines = []
    for line in text.split('\n'):
        clean_line = re.sub(r'[ \t]+', ' ', line).strip()
        if clean_line:
            lines.append(clean_line)
    
    return '\n'.join(lines)


def detect_invoice_item_zone(cleaned_text: str) -> str:
    """
    Detect invoice item area.
    Simple implementation: return everything after table header.
    """
    # Look for table start
    lines = cleaned_text.split('\n')
    
    # Find first line with pipe characters (table indicator)
    start_idx = 0
    for i, line in enumerate(lines):
        if line.count('|') >= 3:
            start_idx = i
            break
    
    # Return from table start to end
    return '\n'.join(lines[start_idx:])


def split_invoice_into_chunks(
    item_zone_text: str,
    max_items_per_chunk: int = 50,
) -> list[str]:
    """
    Split invoice items into chunks.
    
    Strategy: Split by lines, group into chunks of ~max_items_per_chunk.
    """
    lines = [line for line in item_zone_text.split('\n') if line.strip()]
    
    if not lines:
        return []
    
    # Estimate: ~3-5 lines per item
    lines_per_chunk = max_items_per_chunk * 4
    
    chunks = []
    for i in range(0, len(lines), lines_per_chunk):
        chunk_lines = lines[i:i + lines_per_chunk]
        chunks.append('\n'.join(chunk_lines))
    
    return chunks


def extract_single_chunk(
    chunk_tuple: tuple[int, str],
    model: ModelTarget,
    currency_db_json: str,
    total_chunks: int,
) -> dict[str, Any]:
    idx, chunk_text = chunk_tuple
    
    prompt = CHUNK_EXTRACTION_PROMPT.format(
        chunk_num=idx + 1,
        total_chunks=total_chunks,
        chunk_text=chunk_text,
        currency_db=currency_db_json,
    )
    
    try:
        runtime = get_runtime_settings()
        
        # Используем быстрые методы напрямую в обход LangExtract
        if model.provider == "cerebras":
            raw_output = _call_cerebras(prompt, model.model_id, runtime.cerebras_api_key, timeout=45)
        elif model.provider == "ollama":
            raw_output = _call_ollama(prompt, model.model_id, runtime.ollama_base_url, timeout=120)
        else: # gemini
            raw_output = _call_gemini(prompt, model.model_id, runtime.gemini_api_key, timeout=90)
            
        validation = validate_invoice_json(raw_output)
        return validation
    except Exception as e:
        return {"is_valid": 0, "error": str(e), "items": [], "count": 0}


def extract_invoice_smart(
    ocr_draft: str,
    model: ModelTarget,
    max_workers: int = 4,
) -> dict[str, Any]:
    """
    Smart invoice extraction with auto-chunking.
    
    Best for: 60+ items (up to 500+)
    Time: ~25-50 seconds (parallel processing)
    """
    t_start = time.perf_counter()
    
    # 1. Clean OCR text
    cleaned = clean_invoice_text(ocr_draft)
    if not cleaned:
        return {"error": "Empty OCR text", "items": [], "count": 0}
    
    # 2. Detect item zone
    item_zone = detect_invoice_item_zone(cleaned)
    if not item_zone:
        return {"error": "No invoice items detected", "items": [], "count": 0}
    
    # 3. Split into chunks
    chunks = split_invoice_into_chunks(item_zone, max_items_per_chunk=50)
    if not chunks:
        return {"error": "Failed to chunk invoice", "items": [], "count": 0}
    
    # 4. Load currency database
    currency_db = load_currency_db()
    currency_db_json = json.dumps(currency_db, ensure_ascii=False)
    
    # 5. Parallel extraction
    def process_chunk(chunk_tuple):
        return extract_single_chunk(
            chunk_tuple,
            model,
            currency_db_json,
            total_chunks=len(chunks),
        )
    
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(process_chunk, enumerate(chunks)))
    
    # 6. Merge results (NO deduplication!)
    all_items = []
    for result in results:
        if result.get("is_valid") and result.get("items"):
            all_items.extend(result["items"])
    
    if not all_items:
        errors = [r.get("error", "") for r in results if r.get("error")]
        return {
            "error": f"All chunks failed: {'; '.join(errors)}",
            "items": [],
            "count": 0,
        }
    
    # 7. Re-number positions
    for i, item in enumerate(all_items, 1):
        item["position"] = i
    
    # 8. Extract header fields
    fields = extract_header_fields(all_items)
    
    # 9. Build result
    duration = round(time.perf_counter() - t_start, 3)
    
    return {
        "fields": fields,
        "items": all_items,
        "count": len(all_items),
        "duration": duration,
        "chunks_processed": len(chunks),
    }
