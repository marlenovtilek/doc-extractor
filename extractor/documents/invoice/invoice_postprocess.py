from __future__ import annotations

from ...normalizers.currency import finalize_items
from .invoice_postprocess_country import (
    _sanitize_country_origin,
    fill_derived_item_fields,
    reconcile_numeric_fields,
    spread_single_country_origin,
)
from .invoice_postprocess_dedup import (
    deduplicate_items,
    filter_ocr_anomalies,
    sort_items_by_position,
)
from .invoice_postprocess_peer import (
    _enrich_from_position_peers,
    _harmonize_position_groups,
    _prune_shadow_rows,
)


_HEADER_FIELDS = (
    "document_date",
    "document_number",
    "country_sender",
    "currency_code",
    "currency_name",
    "country_origin",
)


def _normalize_position_value(value) -> int | None:
    try:
        position = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if position is None or position <= 0:
        return None
    return position


def _assign_display_positions(items: list[dict]) -> list[dict]:
    if not items:
        return items

    explicit_positions = [
        _normalize_position_value(item.get("position"))
        for item in items
    ]
    explicit_positions = [position for position in explicit_positions if position is not None]
    unique_positions = sorted(set(explicit_positions))

    unstable_positions = len(items) >= 8 and (
        not unique_positions
        or max(unique_positions) > max(len(items) * 2, 500)
        or len(unique_positions) < max(3, int(len(items) * 0.7))
    )

    if unstable_positions:
        for index, item in enumerate(items, start=1):
            item["position"] = index
        return items

    used_positions: set[int] = set()
    next_position = 1
    for item in items:
        position = _normalize_position_value(item.get("position"))
        if position is not None and position not in used_positions:
            item["position"] = position
            used_positions.add(position)
            next_position = max(next_position, position + 1)
            continue

        while next_position in used_positions:
            next_position += 1
        item["position"] = next_position
        used_positions.add(next_position)
        next_position += 1

    return items


def _drop_positionless_residuals(items: list[dict]) -> list[dict]:
    if not items:
        return items

    explicit_positions = [
        _normalize_position_value(item.get("position"))
        for item in items
    ]
    explicit_positions = [position for position in explicit_positions if position is not None]
    if not explicit_positions:
        return items

    unique_positions = sorted(set(explicit_positions))
    if not unique_positions:
        return items

    expected = list(range(1, unique_positions[-1] + 1))
    positions_are_dense = unique_positions == expected
    if not positions_are_dense:
        return items

    return [item for item in items if _normalize_position_value(item.get("position")) is not None]


def post_fill_from_header(items: list[dict], header_meta: dict, currency_db: list[dict]) -> list[dict]:
    if not header_meta:
        return items

    header_currency_code = header_meta.get("currency_code")
    header_currency_name = header_meta.get("currency_name")

    for item in items:
        for field in _HEADER_FIELDS:
            current = item.get(field)
            is_empty = current is None or str(current).strip().lower() in (
                "",
                "null",
                "none",
                "0",
                "неизвестно",
                "unknown",
            )
            if is_empty and field in header_meta:
                item[field] = header_meta[field]

        if not item.get("currency_code") and header_currency_code:
            item["currency_code"] = header_currency_code
        if not item.get("currency_name") and header_currency_name:
            item["currency_name"] = header_currency_name

    return items


def _apply_header_and_currency_stages(
    items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
) -> list[dict]:
    items = post_fill_from_header(items, header_meta, currency_db)
    items = fill_derived_item_fields(items)
    items = spread_single_country_origin(items)
    items = finalize_items(items, currency_db)
    return fill_derived_item_fields(items)


def _apply_peer_repair_stages(items: list[dict]) -> list[dict]:
    items = _enrich_from_position_peers(items)
    items = fill_derived_item_fields(items)
    items = reconcile_numeric_fields(items)
    return _harmonize_position_groups(items)


def _apply_dedup_and_shadow_stages(
    items: list[dict],
    *,
    preserve_exact_line_duplicates: bool,
) -> list[dict]:
    items = filter_ocr_anomalies(items)
    items = deduplicate_items(
        items,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )
    items = _prune_shadow_rows(items)
    return deduplicate_items(
        items,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )


def _annotate_item_quality(items: list[dict]) -> list[dict]:
    def _is_meaningful_decl_ref(value) -> bool:
        text = str(value or "").strip()
        return bool(text and text.lower() not in {"", "null", "none"})

    def _collect_review_notes(item: dict) -> list[str]:
        notes: list[str] = []
        description = str(item.get("description") or "").strip()
        hs_code = str(item.get("hs_code") or "").strip()
        country_origin = str(item.get("country_origin") or "").strip()

        if not hs_code:
            notes.append("missing_hs_code")
        if not country_origin:
            notes.append("missing_country_origin")
        if len(description) < 5:
            notes.append("short_description")
        if item.get("_peer_hydrated"):
            notes.append("peer_repaired")
        if not hs_code and _is_meaningful_decl_ref(item.get("_decl_ref")):
            notes.append("declaration_reference_present")
        return notes

    def _derive_confidence(notes: list[str]) -> str:
        if not notes:
            return "high"
        core_notes = {"missing_hs_code", "missing_country_origin"}
        non_core_notes = [note for note in notes if note not in core_notes]
        if len(notes) == 1 and notes[0] in core_notes:
            return "medium"
        if not any(note in core_notes for note in notes) and non_core_notes:
            return "medium"
        return "low"

    def _derive_review_priority(notes: list[str]) -> str:
        if not notes:
            return "none"
        if "missing_hs_code" in notes or "missing_country_origin" in notes:
            return "high"
        return "medium"

    annotated: list[dict] = []

    for item in items:
        out = dict(item)
        notes = _collect_review_notes(out)
        confidence = _derive_confidence(notes)
        review_priority = _derive_review_priority(notes)

        out["parsing_confidence"] = confidence
        out["review_required"] = bool(notes)
        out["review_priority"] = review_priority
        out["review_reason_count"] = len(notes)
        out["review_notes"] = ", ".join(notes) if notes else None
        annotated.append(out)

    return annotated


def _strip_internal_fields(items: list[dict]) -> list[dict]:
    for item in items:
        for field in list(item):
            if field.startswith("_"):
                item.pop(field, None)
    return items


def normalize_invoice_items(
    items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
    *,
    preserve_exact_line_duplicates: bool = False,
    annotate_review: bool = True,
    strip_internal_fields: bool = True,
    sort_output: bool = True,
) -> list[dict]:
    normalized = _apply_header_and_currency_stages(items, header_meta, currency_db)
    normalized = _apply_peer_repair_stages(normalized)
    normalized = _apply_dedup_and_shadow_stages(
        normalized,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )
    normalized = _drop_positionless_residuals(normalized)
    normalized = _assign_display_positions(normalized)
    if annotate_review:
        normalized = _annotate_item_quality(normalized)
    if strip_internal_fields:
        normalized = _strip_internal_fields(normalized)
    if sort_output:
        return sort_items_by_position(normalized)
    return normalized


def merge_normalized_invoice_items(
    items: list[dict],
    *,
    preserve_exact_line_duplicates: bool = False,
) -> list[dict]:
    merged = _apply_peer_repair_stages(items)
    merged = _apply_dedup_and_shadow_stages(
        merged,
        preserve_exact_line_duplicates=preserve_exact_line_duplicates,
    )
    merged = _drop_positionless_residuals(merged)
    merged = _assign_display_positions(merged)
    merged = _annotate_item_quality(merged)
    merged = _strip_internal_fields(merged)
    return sort_items_by_position(merged)


def prepare_invoice_items_for_merge(
    items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
) -> list[dict]:
    prepared = _apply_header_and_currency_stages(items, header_meta, currency_db)
    return _apply_peer_repair_stages(prepared)
