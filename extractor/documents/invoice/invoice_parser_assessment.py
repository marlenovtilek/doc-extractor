from __future__ import annotations

import re

from .invoice_cleaner import _is_table_item_line, _table_cells
from .invoice_parser_support import _build_structured_line_signature


def _count_candidate_table_rows(cleaned_context: str) -> int:
    if not cleaned_context:
        return 0
    body = cleaned_context.split("=== INVOICE CONTENT ===\n", 1)[-1]
    return sum(1 for line in body.splitlines() if _is_table_item_line(line))


def _candidate_row_signature(line: str) -> tuple[str, ...] | None:
    if not _is_table_item_line(line):
        return None

    cells = _table_cells(line)
    if not cells:
        return None

    normalized: list[str] = []
    for cell in cells[:12]:
        text = str(cell or "").strip().lower()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\w.,/\- ]", "", text)
        normalized.append(text)

    if not normalized:
        return None
    return tuple(normalized)


def _count_unique_candidate_table_rows(cleaned_context: str) -> int:
    if not cleaned_context:
        return 0

    body = cleaned_context.split("=== INVOICE CONTENT ===\n", 1)[-1]
    signatures = {
        signature
        for line in body.splitlines()
        for signature in [_candidate_row_signature(line)]
        if signature is not None
    }
    return len(signatures)


def _structured_item_is_complete(item: dict) -> bool:
    required = ("description", "quantity", "cost", "price")
    for field in required:
        value = item.get(field)
        if value in (None, "", "null", "none", 0, 0.0):
            return False
    if item.get("position") is None:
        return False
    return bool(item.get("hs_code") or item.get("country_origin"))


def _is_summary_like_item_line(line: str) -> bool:
    lower = line.lower()
    return any(
        token in lower
        for token in ("резюме", "итого", "summary", "общее число единиц", "total amount")
    )


def _collect_line_level_repair_candidates(
    cleaned_context: str,
    structured_items: list[dict],
    *,
    max_lines: int = 12,
) -> list[str]:
    body = cleaned_context.split("=== INVOICE CONTENT ===\n", 1)[-1]
    parsed_signatures = {
        tuple(item.get("_line_sig") or ())
        for item in structured_items
        if item.get("_line_sig")
    }

    candidates: list[str] = []
    for line in body.splitlines():
        if not _is_table_item_line(line) or _is_summary_like_item_line(line):
            continue
        signature = _build_structured_line_signature(_table_cells(line))
        if not signature or signature in parsed_signatures:
            continue
        if len(signature) > 1 and signature[1:] in parsed_signatures:
            continue
        candidates.append(line)
        if len(candidates) >= max_lines:
            break
    return candidates


def _assess_structured_parser(cleaned_context: str, structured_items: list[dict]) -> dict[str, float | int | bool]:
    if not structured_items:
        return {
            "use_parser_first": False,
            "candidate_rows": 0,
            "candidate_rows_raw": 0,
            "parsed_items": 0,
            "unique_positions": 0,
            "coverage_ratio": 0.0,
            "completeness_ratio": 0.0,
            "duplicate_inflation_ratio": 0.0,
        }

    candidate_rows_raw = _count_candidate_table_rows(cleaned_context)
    candidate_rows = _count_unique_candidate_table_rows(cleaned_context)
    unique_positions = len(
        {
            int(item["position"])
            for item in structured_items
            if item.get("position") is not None
        }
    )
    complete_items = sum(1 for item in structured_items if _structured_item_is_complete(item))
    completeness_ratio = round(complete_items / len(structured_items), 3)
    denominator = max(candidate_rows, unique_positions, 1)
    coverage_ratio = round(unique_positions / denominator, 3)
    duplicate_inflation_ratio = round(candidate_rows_raw / max(candidate_rows, 1), 3)
    use_parser_first = (
        unique_positions >= 15
        and completeness_ratio >= 0.8
        and (
            coverage_ratio >= 0.35
            or unique_positions >= 40
            or duplicate_inflation_ratio >= 1.5
        )
    )
    return {
        "use_parser_first": use_parser_first,
        "candidate_rows": candidate_rows,
        "candidate_rows_raw": candidate_rows_raw,
        "parsed_items": len(structured_items),
        "unique_positions": unique_positions,
        "coverage_ratio": coverage_ratio,
        "completeness_ratio": completeness_ratio,
        "duplicate_inflation_ratio": duplicate_inflation_ratio,
    }
