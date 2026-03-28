from __future__ import annotations

import re

from ...normalizers.currency import resolve_country_code
from .invoice_cleaner import _parse_loose_number, normalize_hs_code


def filter_ocr_anomalies(items: list[dict]) -> list[dict]:
    filtered: list[dict] = []

    def _line_sig_first(item: dict) -> str | None:
        line_sig = item.get("_line_sig")
        if isinstance(line_sig, tuple) and line_sig:
            return str(line_sig[0]).strip()
        return None

    def _markerish_token_count(item: dict) -> int:
        line_sig = item.get("_line_sig")
        if not isinstance(line_sig, tuple):
            return 0
        count = 0
        for token in line_sig:
            text = str(token or "").strip().lower()
            if not text:
                continue
            if re.fullmatch(r"[•*.,/_\- ]+", text):
                count += 1
        return count

    def _has_invalid_compact_country_token(item: dict) -> bool:
        line_sig = item.get("_line_sig")
        if not isinstance(line_sig, tuple):
            return False
        for token in line_sig[1:6]:
            text = str(token or "").strip()
            compact = re.sub(r"[^A-Za-z]", "", text).upper()
            if not 2 <= len(compact) <= 3:
                continue
            if resolve_country_code(compact) is None:
                return True
        return False

    def _looks_like_marker_shadow_description(value) -> bool:
        text = str(value or "").strip()
        if not text or re.search(r"[А-Яа-яЁё]", text):
            return False
        if len(text) > 18:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9 .,'\"()/-]+", text))

    def _is_explicit_small_pos_row(item: dict) -> bool:
        raw_position = item.get("position")
        try:
            position = int(raw_position) if raw_position is not None else None
        except (TypeError, ValueError):
            return False
        if position is None or not (0 < position <= 500):
            return False
        return _line_sig_first(item) == str(position)

    def _has_reviewable_payload(item: dict) -> bool:
        description = str(item.get("description") or "").strip()
        if len(description) < 3:
            return False
        if item.get("part_no") or item.get("hs_code"):
            return True
        return any(
            _parse_loose_number(item.get(field)) not in (None, 0.0)
            for field in ("quantity", "cost", "price")
        )

    def _is_zero_total_service_row(
        item: dict,
        *,
        quantity: float | None,
        cost: float | None,
        price: float | None,
    ) -> bool:
        description = str(item.get("description") or "").strip()
        compact_description = re.sub(r"[^\wА-Яа-яЁё]", "", description)
        if len(compact_description) < 5:
            return False
        if quantity is None or quantity <= 0:
            return False
        if cost is None or price is None:
            return False
        if abs(cost) > 0.001 or abs(price) > 0.001:
            return False
        return not str(item.get("hs_code") or "").strip()

    for item in items:
        out = dict(item)

        raw_position = out.get("position")
        if raw_position is not None:
            try:
                position = int(raw_position)
            except (TypeError, ValueError):
                continue
            if position <= 0:
                continue
            out["position"] = position

        out["hs_code"] = normalize_hs_code(out.get("hs_code"))

        raw_sig_first = _line_sig_first(out)
        if (
            out["hs_code"] is not None
            and raw_sig_first
            and raw_sig_first.startswith("0")
            and _has_invalid_compact_country_token(out)
        ):
            continue
        if (
            out["hs_code"] is not None
            and _markerish_token_count(out) >= 2
            and _looks_like_marker_shadow_description(out.get("description"))
        ):
            continue

        quantity = _parse_loose_number(out.get("quantity"))
        cost = _parse_loose_number(out.get("cost"))
        price = _parse_loose_number(out.get("price"))
        if quantity is None or cost is None or price is None:
            if _is_explicit_small_pos_row(out) and _has_reviewable_payload(out):
                filtered.append(out)
            continue
        if quantity <= 0 or cost <= 0 or price <= 0:
            if _is_explicit_small_pos_row(out) and _is_zero_total_service_row(
                out,
                quantity=quantity,
                cost=cost,
                price=price,
            ):
                out["quantity"] = quantity
                out["cost"] = cost
                out["price"] = price
                filtered.append(out)
                continue
            if _is_explicit_small_pos_row(out) and _has_reviewable_payload(out):
                filtered.append(out)
            continue

        expected_total = quantity * cost
        if expected_total > 0:
            ratio = price / expected_total
            if ratio < 0.05 or ratio > 20:
                if _is_explicit_small_pos_row(out) and _has_reviewable_payload(out):
                    filtered.append(out)
                continue

        out["quantity"] = quantity
        out["cost"] = cost
        out["price"] = price
        filtered.append(out)

    return filtered


def deduplicate_items(
    items: list[dict],
    *,
    preserve_exact_line_duplicates: bool = False,
) -> list[dict]:
    if not items:
        return items

    empty_values = {"", "null", "none"}

    def _is_empty(value) -> bool:
        return value is None or str(value).strip().lower() in empty_values

    def _is_cyrillic(text: str) -> bool:
        return bool(re.search(r"[А-Яа-яёЁ]", str(text or "")))

    def _looks_like_noisy_latin_description(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw or _is_cyrillic(raw):
            return False
        letters = [ch for ch in raw if ch.isalpha()]
        if len(letters) < 8:
            return False
        uppercase_ratio = sum(ch.isupper() for ch in letters) / max(len(letters), 1)
        words = re.findall(r"[A-Za-z]{3,}", raw)
        if len(words) < 2:
            return False
        return uppercase_ratio >= 0.75

    def _norm_num(value, decimals: int = 2) -> float:
        try:
            return round(float(value or 0), decimals)
        except (TypeError, ValueError):
            return 0.0

    def _norm_hs(value) -> str | None:
        if _is_empty(value):
            return None
        return str(value).strip()

    def _norm_decl_ref(value) -> str | None:
        if _is_empty(value):
            return None
        digits = re.sub(r"\D", "", str(value))
        return digits or None

    def _line_sig_first(item: dict) -> str | None:
        line_sig = item.get("_line_sig")
        if isinstance(line_sig, tuple) and line_sig:
            return str(line_sig[0]).strip()
        return None

    def _has_complete_numeric_payload(item: dict) -> bool:
        return (
            _norm_num(item.get("quantity"), 3) > 0
            and _norm_num(item.get("cost")) > 0
            and _norm_num(item.get("price")) > 0
        )

    def _line_sig_has_numeric_payload(item: dict) -> bool:
        line_sig = item.get("_line_sig")
        if not isinstance(line_sig, tuple):
            return False
        numeric_tokens = 0
        for token in line_sig:
            if re.search(r"\d", str(token or "")):
                numeric_tokens += 1
        return numeric_tokens >= 3

    def _same_explicit_position(item: dict) -> bool:
        raw_pos = item.get("position")
        try:
            position = int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            return False
        if position is None:
            return False
        return _line_sig_first(item) == str(position)

    def _make_key(item: dict) -> tuple | None:
        line_sig = item.get("_line_sig")
        if preserve_exact_line_duplicates and isinstance(line_sig, tuple) and line_sig:
            return None
        if isinstance(line_sig, tuple) and line_sig:
            return ("line",) + line_sig
        raw_pos = item.get("position")
        try:
            pos = int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if pos is None:
            return None
        decl_ref = item.get("_decl_ref")
        if decl_ref is not None:
            decl_ref = re.sub(r"\D", "", str(decl_ref))
            if not decl_ref:
                decl_ref = None
        return (
            pos,
            _norm_hs(item.get("hs_code")),
            _norm_num(item.get("quantity"), 3),
            _norm_num(item.get("price")),
            decl_ref,
        )

    def _make_soft_key(item: dict) -> tuple | None:
        raw_pos = item.get("position")
        try:
            pos = int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if pos is None:
            return None

        quantity = _norm_num(item.get("quantity"), 3)
        cost = _norm_num(item.get("cost"))
        price = _norm_num(item.get("price"))
        if quantity <= 0 or cost <= 0 or price <= 0:
            return None

        return (pos, quantity, cost, price)

    def _hs_conflict(a: dict, b: dict) -> bool:
        hs_a = _norm_hs(a.get("hs_code"))
        hs_b = _norm_hs(b.get("hs_code"))
        return hs_a is not None and hs_b is not None and hs_a != hs_b

    def _merge(base: dict, new: dict) -> dict:
        out = dict(base)
        current_desc = str(out.get("description", "") or "").strip()
        new_desc = str(new.get("description", "") or "").strip()
        if new_desc and (
            (_is_cyrillic(new_desc) and not _is_cyrillic(current_desc))
            or (_looks_like_noisy_latin_description(current_desc) and not _looks_like_noisy_latin_description(new_desc))
            or (len(new_desc) > len(current_desc) and (_is_cyrillic(new_desc) or not current_desc))
        ):
            out["description"] = new_desc
        for field in (
            "hs_code",
            "country_origin",
            "country_origin_code",
            "currency_code",
            "currency_name",
            "document_date",
            "document_number",
            "country_sender",
        ):
            if _is_empty(out.get(field)) and not _is_empty(new.get(field)):
                out[field] = new[field]
        for field in ("cost", "price", "quantity"):
            if _norm_num(out.get(field)) == 0.0 and _norm_num(new.get(field)) != 0.0:
                out[field] = new[field]
        return out

    seen: dict[tuple, int] = {}
    soft_seen: dict[tuple, int] = {}
    result: list[dict] = []

    for item in items:
        soft_key = _make_soft_key(item)
        if soft_key is not None and soft_key in soft_seen:
            existing_idx = soft_seen[soft_key]
            existing = result[existing_idx]
            existing_hs = _norm_hs(existing.get("hs_code"))
            current_hs = _norm_hs(item.get("hs_code"))
            hydrated_shadow = bool(existing.get("_peer_hydrated") or item.get("_peer_hydrated"))
            decl_refs_compatible = (
                _norm_decl_ref(existing.get("_decl_ref")) is None
                or _norm_decl_ref(item.get("_decl_ref")) is None
                or _norm_decl_ref(existing.get("_decl_ref")) == _norm_decl_ref(item.get("_decl_ref"))
            )
            if preserve_exact_line_duplicates:
                existing_first = _line_sig_first(existing)
                current_first = _line_sig_first(item)
                if (
                    existing_first
                    and current_first
                    and existing_first == current_first
                    and _has_complete_numeric_payload(existing)
                    and _has_complete_numeric_payload(item)
                    and _line_sig_has_numeric_payload(existing)
                    and _line_sig_has_numeric_payload(item)
                ):
                    hydrated_shadow = False
            if decl_refs_compatible and _same_explicit_position(existing) and _same_explicit_position(item):
                hydrated_shadow = True
            if not _hs_conflict(item, existing) and (
                existing_hs is None or current_hs is None or hydrated_shadow
            ):
                result[existing_idx] = _merge(existing, item)
                continue

        key = _make_key(item)
        if key is None:
            result.append(item)
            if soft_key is not None and soft_key not in soft_seen:
                soft_seen[soft_key] = len(result) - 1
            continue
        if key in seen:
            existing_idx = seen[key]
            existing = result[existing_idx]
            if _hs_conflict(item, existing):
                result.append(item)
                if soft_key is not None and soft_key not in soft_seen:
                    soft_seen[soft_key] = len(result) - 1
            else:
                result[existing_idx] = _merge(existing, item)
        else:
            seen[key] = len(result)
            result.append(item)
            if soft_key is not None and soft_key not in soft_seen:
                soft_seen[soft_key] = len(result) - 1

    hs_soft_keys = {
        _make_soft_key(item)
        for item in result
        if _norm_hs(item.get("hs_code")) is not None
    }
    hs_soft_keys.discard(None)

    filtered_result: list[dict] = []
    for item in result:
        if _norm_hs(item.get("hs_code")) is not None:
            filtered_result.append(item)
            continue
        soft_key = _make_soft_key(item)
        if soft_key is not None and soft_key in hs_soft_keys:
            continue
        filtered_result.append(item)

    return filtered_result


def sort_items_by_position(items: list[dict]) -> list[dict]:
    if not items:
        return items

    indexed_items = list(enumerate(items))

    def _sort_key(entry: tuple[int, dict]) -> tuple[int, int, int]:
        original_idx, item = entry
        raw_pos = item.get("position")
        try:
            pos = int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if pos is None:
            return (1, 0, original_idx)
        return (0, pos, original_idx)

    return [item for _, item in sorted(indexed_items, key=_sort_key)]
