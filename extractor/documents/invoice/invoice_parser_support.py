from __future__ import annotations

import re

from ...normalizers.currency import resolve_country_code
from .invoice_cleaner import (
    _is_article_like_cell,
    _is_country_like_cell,
    _is_declaration_like_cell,
    _is_hs_like_cell,
    _is_marker_like_cell,
    _is_numericish_cell,
    _is_pure_code_like_cell,
    _is_terminal_hs_cell,
    _parse_loose_number,
)

_COUNTRY_PARSE_TRANSLATION = str.maketrans(
    {
        "Ι": "I",
        "Ϊ": "I",
        "І": "I",
        "Τ": "T",
    }
)

_COUNTRY_DIGIT_TRANSLATION = str.maketrans(
    {
        "0": "O",
        "1": "I",
        "3": "S",
        "5": "S",
        "8": "B",
    }
)
_COUNTRY_EDGE_NOISE_CHARS = frozenset({"I", "L", "X"})


def _normalize_country_token(value: str) -> str:
    return str(value or "").translate(_COUNTRY_PARSE_TRANSLATION).strip()


def _normalize_compact_country_code(value: str) -> str | None:
    text = _normalize_country_token(value)
    if not text:
        return None

    compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    if not 2 <= len(compact) <= 3:
        return None

    candidates = [compact]
    translated = compact.translate(_COUNTRY_DIGIT_TRANSLATION)
    if translated not in candidates:
        candidates.append(translated)

    for candidate in list(candidates):
        if resolve_country_code(candidate) is not None:
            return candidate
        if len(candidate) == 3:
            if candidate[0] in _COUNTRY_EDGE_NOISE_CHARS and resolve_country_code(candidate[1:]) is not None:
                return candidate[1:]
            if candidate[-1] in _COUNTRY_EDGE_NOISE_CHARS and resolve_country_code(candidate[:-1]) is not None:
                return candidate[:-1]
    return None


def _normalized_article_digits(value: str) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if re.fullmatch(r"\d{4,14}", text):
        return text
    repeated = re.fullmatch(r"(\d{4,14})(?:\s+\1)+", text)
    if repeated:
        return repeated.group(1)
    return None


def _is_specific_country_cell(value: str) -> bool:
    text = _normalize_country_token(value)
    if not text:
        return False

    compact_code = _normalize_compact_country_code(text)
    if compact_code is not None:
        return True

    if not _is_country_like_cell(text) or re.search(r"\d", text):
        return False

    compact_latin = re.sub(r"[^A-Za-z]", "", text).upper()
    if 2 <= len(compact_latin) <= 3:
        return True

    words = re.findall(r"[A-Za-zА-Яа-яЁё]+", text)
    if not words or len(words) > 2:
        return False

    if any(len(word) > 20 for word in words):
        return False
    return True


def _pick_cost_price_pair(quantity: float, tail_cells: list[str]) -> tuple[float, float] | None:
    if quantity <= 0:
        return None

    numeric_cells: list[tuple[int, float]] = []
    for idx, cell in enumerate(tail_cells[1:], start=1):
        value = _parse_loose_number(cell)
        if value is None or value <= 0:
            continue
        numeric_cells.append((idx, value))

    best_pair: tuple[tuple[float, int, int], tuple[float, float]] | None = None
    for i, (cost_idx, cost) in enumerate(numeric_cells):
        for price_idx, price in numeric_cells[i + 1 :]:
            if price < cost:
                continue
            expected_total = quantity * cost
            rel_err = abs(price - expected_total) / max(expected_total, price, 1.0)
            score = (rel_err, -price_idx, -cost_idx)
            if best_pair is None or score < best_pair[0]:
                best_pair = (score, (cost, price))

    if best_pair is None:
        return None
    if best_pair[0][0] > 0.45:
        return None
    return best_pair[1]


def _is_reasonable_quantity(value: float | None) -> bool:
    return value is not None and 0 < value <= 1000


def _is_integerish_quantity(value: float | None) -> bool:
    if value is None:
        return False
    if value < 1:
        return False
    return abs(value - round(value)) <= 0.05


def _parse_small_integer_hint(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    groups = re.findall(r"\d+", text)
    if not groups:
        return None

    if "/" in text or "-" in text:
        for group in groups:
            parsed = int(group)
            if 0 < parsed <= 10:
                return float(parsed)

    if len(groups) == 1:
        parsed = int(groups[0])
        if 0 < parsed <= 10 and len(text) <= 4:
            return float(parsed)
    return None


def _salvage_quantity_cost_price(
    quantity_hint: float | None,
    tail_cells: list[str],
) -> tuple[float, float, float] | None:
    numeric_cells = [_parse_loose_number(cell) for cell in tail_cells]
    numeric_values = [value for value in numeric_cells if value is not None and value > 0]
    if len(numeric_values) < 2:
        return None

    total = numeric_values[-1]
    previous_values = numeric_values[:-1]
    if not previous_values:
        return None

    if (
        _is_reasonable_quantity(quantity_hint)
        and _is_integerish_quantity(quantity_hint)
        and quantity_hint >= 1
        and total >= max(previous_values)
    ):
        derived_cost = round(total / quantity_hint, 4)
        if derived_cost > 0:
            return float(quantity_hint), derived_cost, total

    if quantity_hint is not None and 0 < quantity_hint < 1:
        scaled_qty = quantity_hint * 10
        if _is_reasonable_quantity(scaled_qty) and _is_integerish_quantity(scaled_qty):
            candidate_costs = list(reversed(previous_values[-3:]))
            for cost in candidate_costs:
                if cost <= 0:
                    continue
                scaled_total = total * 10
                expected_total = scaled_qty * cost
                rel_err = abs(scaled_total - expected_total) / max(expected_total, scaled_total, 1.0)
                if rel_err <= 0.18 and scaled_total >= cost:
                    return float(round(scaled_qty)), cost, round(scaled_total, 4)
        return None

    candidate_costs = list(reversed(previous_values[-3:]))
    best_match: tuple[float, float, float] | None = None
    best_distance: float | None = None
    for cost in candidate_costs:
        if cost <= 0 or cost >= total:
            continue
        inferred_qty = total / cost
        if not 0 < inferred_qty <= 1000:
            continue
        rounded_qty = round(inferred_qty)
        distance = abs(inferred_qty - rounded_qty)
        if distance > 0.12:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_match = (float(rounded_qty), cost, total)
    return best_match


def _pick_quantity_cost_price(
    quantity_hint: float | None,
    tail_cells: list[str],
) -> tuple[float, float, float] | None:
    if _is_reasonable_quantity(quantity_hint) and _is_integerish_quantity(quantity_hint):
        pair = _pick_cost_price_pair(float(quantity_hint), tail_cells)
        if pair is not None:
            return float(quantity_hint), pair[0], pair[1]
        return _salvage_quantity_cost_price(quantity_hint, tail_cells)
    salvage_hint = quantity_hint if quantity_hint is not None and 0 < quantity_hint < 1 else None
    return _salvage_quantity_cost_price(salvage_hint, tail_cells)


def _pick_structured_description(cells: list[str]) -> str:
    candidates = [str(cell or "").strip() for cell in cells if str(cell or "").strip()]
    if not candidates:
        return ""

    cyrillic_candidates = [cell for cell in candidates if re.search(r"[А-Яа-яЁё]", cell)]
    if cyrillic_candidates:
        return max(cyrillic_candidates, key=len)
    return max(candidates, key=len)


def _is_loose_numeric_value_cell(value: str) -> bool:
    text = str(value or "").strip()
    if not text or _is_article_like_cell(text) or _is_pure_code_like_cell(text):
        return False
    parsed = _parse_loose_number(text)
    return parsed is not None and parsed > 0


def _join_structured_description(cells: list[str]) -> str:
    parts: list[str] = []
    for cell in cells:
        text = str(cell or "").strip()
        if not text:
            continue
        if _is_hs_like_cell(text) or _is_declaration_like_cell(text):
            continue
        if _is_numericish_cell(text):
            continue
        parts.append(text)
    if not parts:
        return ""
    return " ".join(parts)


def _extract_declaration_ref(cells: list[str]) -> str | None:
    for cell in cells:
        text = str(cell or "").strip()
        if _is_declaration_like_cell(text):
            return re.sub(r"\D", "", text)
    return None


def _build_structured_line_signature(cells: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for cell in cells[:12]:
        text = str(cell or "").strip().lower()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_country_origin_hint(value: str) -> str | None:
    text = _normalize_country_token(value)
    if not text:
        return None

    split_tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", text.upper())
        if 2 <= len(token) <= 3
    ]
    for token in split_tokens:
        compact_token = _normalize_compact_country_code(token)
        if compact_token is not None:
            return compact_token

    compact_code = _normalize_compact_country_code(text)
    if compact_code is not None:
        return compact_code
    return None


def _normalized_country_value(value: str) -> str:
    normalized = _normalize_country_origin_hint(value)
    if normalized is not None:
        return normalized
    return str(value or "").strip()


def _extract_position_from_cells(cells: list[str]) -> int | None:
    if not cells:
        return None

    work = [str(cell or "").strip() for cell in cells if str(cell or "").strip()]
    if not work:
        return None

    if _has_explicit_pos_part_no_layout(work):
        digits = re.sub(r"\D", "", work[0])
        if digits:
            return int(digits)

    if len(work) >= 2 and _is_marker_like_cell(work[0]) and _is_article_like_cell(work[1]):
        normalized_article = _normalized_article_digits(work[1])
        if normalized_article is not None:
            return int(normalized_article)

    normalized_article = _normalized_article_digits(work[0])
    if normalized_article is not None:
        return int(normalized_article)
    return None


def _has_explicit_pos_part_no_layout(cells: list[str]) -> bool:
    work = [str(cell or "").strip() for cell in cells if str(cell or "").strip()]
    if len(work) < 2:
        return False
    return re.fullmatch(r"\d{1,3}", work[0]) is not None and _is_article_like_cell(work[1])


def _extract_part_no_from_cells(cells: list[str]) -> str | None:
    work = [str(cell or "").strip() for cell in cells if str(cell or "").strip()]
    if not work:
        return None

    if _has_explicit_pos_part_no_layout(work):
        return _normalized_article_digits(work[1]) or work[1]

    if len(work) >= 2 and _is_marker_like_cell(work[0]) and _is_article_like_cell(work[1]):
        return _normalized_article_digits(work[1]) or work[1]

    if _is_article_like_cell(work[0]):
        return _normalized_article_digits(work[0]) or work[0]

    return None


def _positionless_companion_matches_item(companion: dict, item: dict) -> bool:
    companion_qty = _parse_loose_number(companion.get("quantity"))
    item_qty = _parse_loose_number(item.get("quantity"))
    companion_price = _parse_loose_number(companion.get("price"))
    item_price = _parse_loose_number(item.get("price"))
    if companion_qty is None or item_qty is None or companion_price is None or item_price is None:
        return False
    if abs(companion_qty - item_qty) > 0.05:
        return False
    return abs(companion_price - item_price) <= max(1.0, 0.03 * max(companion_price, item_price))


def _find_terminal_hs_index(cells: list[str]) -> int | None:
    for idx in range(len(cells) - 1, 1, -1):
        if not _is_terminal_hs_cell(cells[idx]):
            continue
        trailing = cells[idx + 1 :]
        if len(trailing) <= 2 and all(
            _is_numericish_cell(cell) or _is_marker_like_cell(cell) for cell in trailing
        ):
            return idx
    return None


def _is_loose_hs_candidate(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 6 <= len(digits) <= 10
