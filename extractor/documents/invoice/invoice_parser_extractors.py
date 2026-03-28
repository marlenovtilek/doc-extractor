from __future__ import annotations

import re

from .invoice_cleaner import (
    _is_article_like_cell,
    _is_declaration_like_cell,
    _is_hs_like_cell,
    _is_marker_like_cell,
    _is_numericish_cell,
    _is_pure_code_like_cell,
    _is_terminal_hs_cell,
    _parse_loose_number,
    normalize_hs_code,
)
from .invoice_parser_support import (
    _build_structured_line_signature,
    _extract_declaration_ref,
    _find_terminal_hs_index,
    _is_integerish_quantity,
    _is_loose_hs_candidate,
    _is_loose_numeric_value_cell,
    _is_reasonable_quantity,
    _is_specific_country_cell,
    _join_structured_description,
    _normalize_country_origin_hint,
    _normalized_country_value,
    _parse_small_integer_hint,
    _pick_cost_price_pair,
    _pick_quantity_cost_price,
    _pick_structured_description,
)


def _extract_shifted_tail_item(cells: list[str], position: int | None) -> dict | None:
    hs_idx = None
    for idx in range(len(cells) - 1, 1, -1):
        if _is_hs_like_cell(cells[idx]) and _is_specific_country_cell(cells[idx - 1]):
            hs_idx = idx
            break
    if hs_idx is None or hs_idx < 3:
        return None

    country_idx = hs_idx - 1
    quantity = _parse_loose_number(cells[hs_idx + 1]) if hs_idx + 1 < len(cells) else None
    if not (_is_reasonable_quantity(quantity) and _is_integerish_quantity(quantity)):
        quantity = None

    total_candidates: list[float] = []
    for cell in cells[1:hs_idx]:
        text = str(cell or "").strip()
        if (
            not _is_numericish_cell(text)
            or _is_pure_code_like_cell(text)
            or _is_article_like_cell(text)
        ):
            continue
        value = _parse_loose_number(cell)
        if value is not None and 0 < value <= 1_000_000:
            total_candidates.append(value)
    for cell in cells[hs_idx + 2 :]:
        text = str(cell or "").strip()
        if (
            not _is_numericish_cell(text)
            or _is_pure_code_like_cell(text)
            or _is_article_like_cell(text)
        ):
            continue
        value = _parse_loose_number(cell)
        if value is not None and 0 < value <= 1_000_000:
            total_candidates.append(value)
    if not total_candidates:
        return None

    total = max(total_candidates)
    if total <= 0:
        return None

    if quantity is None:
        tail_quantity_hints = [_parse_small_integer_hint(cell) for cell in cells[hs_idx + 2 :]]
        tail_quantity_hints = [hint for hint in tail_quantity_hints if hint is not None]
        if tail_quantity_hints:
            quantity = tail_quantity_hints[-1]
        else:
            return None

    cost = round(total / quantity, 4)
    if cost <= 0:
        return None

    trailing_numeric = [
        _parse_loose_number(cell)
        for cell in cells[hs_idx + 1 :]
        if _parse_loose_number(cell) is not None and _parse_loose_number(cell) > 0
    ]
    if len(trailing_numeric) >= 2:
        trailing_cost = trailing_numeric[-2]
        trailing_price = trailing_numeric[-1]
        leading_noise = trailing_numeric[:-2]
        max_leading_noise = max(leading_noise) if leading_noise else 0.0
        if (
            trailing_price == total
            and trailing_price >= trailing_cost > 0
            and trailing_cost >= max(max_leading_noise * 3, 20.0)
        ):
            cost = trailing_cost
            total = trailing_price

    description = _join_structured_description(cells[1:country_idx])
    if not description:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": total,
        "country_origin": _normalized_country_value(cells[country_idx]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _infer_quantity_from_cost_and_total(cost: float, price: float) -> float | None:
    if cost <= 0 or price <= 0:
        return None
    ratio = price / cost
    rounded = round(ratio)
    if 1 <= rounded <= 500 and abs(ratio - rounded) <= max(0.05, 0.03 * rounded):
        return float(rounded)
    if abs(price - cost) <= max(0.05, cost * 0.02):
        return 1.0
    return None


def _parse_quantityish_cell(value: str) -> float | None:
    parsed = _parse_loose_number(value)
    if _is_reasonable_quantity(parsed) and _is_integerish_quantity(parsed):
        return float(round(parsed))

    groups = re.findall(r"\d+", str(value or ""))
    if not groups:
        return None

    primary = int(groups[0])
    if 0 < primary <= 1000:
        return float(primary)
    return None


def _pick_sparse_quantity_cost_price(tail_cells: list[str]) -> tuple[float, float, float] | None:
    for idx, cell in enumerate(tail_cells[:-1]):
        quantity = _parse_quantityish_cell(cell)
        if not (_is_reasonable_quantity(quantity) and _is_integerish_quantity(quantity)):
            continue
        pair = _pick_cost_price_pair(float(quantity), tail_cells[idx:])
        if pair is not None:
            return float(quantity), pair[0], pair[1]

    if len(tail_cells) == 2:
        quantity = _parse_quantityish_cell(tail_cells[0])
        cost = _parse_loose_number(tail_cells[1])
        if (
            _is_reasonable_quantity(quantity)
            and _is_integerish_quantity(quantity)
            and cost is not None
            and cost > 0
        ):
            return float(quantity), cost, round(float(quantity) * cost, 4)
    return None


def _extract_hs_last_item(cells: list[str], position: int | None) -> dict | None:
    hs_idx = _find_terminal_hs_index(cells)
    if len(cells) < 7 or hs_idx is None:
        return None
    if hs_idx != len(cells) - 1 and _is_specific_country_cell(cells[hs_idx - 1]):
        return None

    country_idx = None
    for idx in range(hs_idx - 1, 0, -1):
        if not _is_specific_country_cell(cells[idx]):
            continue
        tail = cells[idx + 1 : hs_idx]
        if len(tail) < 2:
            continue
        numericish = sum(_is_numericish_cell(cell) for cell in tail)
        if numericish >= 2:
            country_idx = idx
            break
    if country_idx is None:
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    if (
        hs_idx != len(cells) - 1
        and _is_article_like_cell(cells[0])
        and description_start == 1
        and len(cells) >= 3
        and _is_specific_country_cell(cells[2])
        and len(re.sub(r"[^A-Za-zА-Яа-яЁё]", "", str(cells[2] or ""))) <= 4
    ):
        return None
    description = _pick_structured_description(cells[description_start:country_idx])
    if not description:
        return None

    tail = cells[country_idx + 1 : hs_idx]
    numeric_tail = [cell for cell in tail if _is_numericish_cell(cell) or _is_loose_numeric_value_cell(cell)]
    if len(numeric_tail) < 2:
        return None

    quantity = None
    cost = None
    price = None
    if len(numeric_tail) >= 3:
        quantity_hint = _parse_loose_number(numeric_tail[0])
        if (
            _is_reasonable_quantity(quantity_hint)
            and _is_integerish_quantity(quantity_hint)
            and quantity_hint >= 1
            and len(numeric_tail) >= 5
        ):
            trailing_cost = _parse_loose_number(numeric_tail[-2])
            trailing_price = _parse_loose_number(numeric_tail[-1])
            leading_noise = [
                _parse_loose_number(cell)
                for cell in numeric_tail[1:-2]
                if _parse_loose_number(cell) is not None
            ]
            max_leading_noise = max(leading_noise) if leading_noise else 0.0
            if (
                trailing_cost is not None
                and trailing_price is not None
                and trailing_cost > 0
                and trailing_price >= trailing_cost
                and trailing_cost >= max(max_leading_noise * 3, 20.0)
            ):
                quantity = float(round(quantity_hint))
                cost = trailing_cost
                price = trailing_price
        picked = _pick_quantity_cost_price(quantity_hint, numeric_tail)
        if quantity is None or cost is None or price is None:
            if picked is None:
                picked = _pick_sparse_quantity_cost_price(numeric_tail)
                if picked is None:
                    return None
            quantity, cost, price = picked
    else:
        cost = _parse_loose_number(numeric_tail[0])
        price = _parse_loose_number(numeric_tail[1])
        if cost is None or price is None or cost <= 0 or price <= 0:
            picked = _pick_sparse_quantity_cost_price(numeric_tail)
            if picked is None:
                return None
            quantity, cost, price = picked
        else:
            quantity = _infer_quantity_from_cost_and_total(cost, price)
            if quantity is None:
                picked = _pick_sparse_quantity_cost_price(numeric_tail)
                if picked is None:
                    return None
                quantity, cost, price = picked

    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": _normalized_country_value(cells[country_idx]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_sparse_hs_item_without_country(cells: list[str], position: int | None) -> dict | None:
    hs_idx = _find_terminal_hs_index(cells)
    if hs_idx is None:
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    numeric_start = hs_idx
    while numeric_start - 1 > description_start and _is_numericish_cell(cells[numeric_start - 1]):
        numeric_start -= 1

    if any(
        _is_specific_country_cell(cell)
        and len(re.sub(r"[^A-Za-zА-Яа-яЁё]", "", str(cell or ""))) <= 4
        for cell in cells[description_start + 1 : numeric_start]
    ):
        return None

    numeric_tail = cells[numeric_start:hs_idx]
    description = _pick_structured_description(cells[description_start:numeric_start])
    if not description:
        return None

    if len(numeric_tail) == 2:
        picked = _pick_sparse_quantity_cost_price(numeric_tail)
        if picked is None:
            return None
        quantity, cost, price = picked
    elif len(numeric_tail) == 3:
        quantity_hint = _parse_loose_number(numeric_tail[0])
        picked = _pick_quantity_cost_price(quantity_hint, numeric_tail)
        if picked is None:
            return None
        quantity, cost, price = picked
    else:
        return None

    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": "Неизвестно",
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_hs_last_single_value_item(cells: list[str], position: int | None) -> dict | None:
    hs_idx = _find_terminal_hs_index(cells)
    if len(cells) < 6 or hs_idx is None or hs_idx != len(cells) - 1:
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    numeric_indices = [
        idx
        for idx in range(description_start + 1, hs_idx)
        if _is_numericish_cell(cells[idx]) and _parse_loose_number(cells[idx]) is not None
    ]
    if len(numeric_indices) != 1:
        return None

    value_idx = numeric_indices[0]
    value = _parse_loose_number(cells[value_idx])
    if value is None or value <= 0:
        return None

    country_idx = None
    for idx in range(description_start + 1, value_idx):
        country = _normalize_country_origin_hint(cells[idx])
        if country is None:
            continue
        country_idx = idx
        break
    if country_idx is None:
        return None

    description = _pick_structured_description(cells[description_start:country_idx])
    if not description or len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) < 4:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": 1.0,
        "unit": "pcs",
        "cost": value,
        "price": value,
        "country_origin": _normalized_country_value(cells[country_idx]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_partial_hs_companion_item(cells: list[str], position: int | None) -> dict | None:
    hs_idx = _find_terminal_hs_index(cells)
    if hs_idx is None or hs_idx != len(cells) - 1:
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    if description_start >= hs_idx:
        return None

    body = [str(cell or "").strip() for cell in cells[description_start:hs_idx] if str(cell or "").strip()]
    if not body:
        return None

    numericish_count = sum(_is_numericish_cell(cell) for cell in body)
    if numericish_count >= 2:
        return None

    country_idx = None
    for idx in range(len(body) - 1, -1, -1):
        if _normalize_country_origin_hint(body[idx]) is not None:
            country_idx = idx
            break

    quantity = None
    quantity_idx = None
    for idx in range(len(body) - 1, -1, -1):
        parsed_qty = _parse_quantityish_cell(body[idx])
        if parsed_qty is None:
            continue
        quantity = parsed_qty
        quantity_idx = idx
        break

    description_cells: list[str] = []
    for idx, cell in enumerate(body):
        if idx == country_idx or idx == quantity_idx:
            continue
        if _is_marker_like_cell(cell):
            continue
        if _is_numericish_cell(cell):
            continue
        description_cells.append(cell)

    description = _pick_structured_description(description_cells)
    if not description or len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) < 3:
        return None

    country_origin = None
    if country_idx is not None:
        country_origin = _normalized_country_value(body[country_idx])

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": None,
        "price": None,
        "country_origin": country_origin,
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
        "_peer_hydrated": True,
    }


def _extract_positionless_marker_hs_last_item(cells: list[str]) -> dict | None:
    if len(cells) < 6 or len(cells) > 8:
        return None
    if _is_article_like_cell(cells[0]) or not _is_marker_like_cell(cells[0]):
        return None

    hs_idx = _find_terminal_hs_index(cells)
    if hs_idx is None or hs_idx != len(cells) - 1:
        return None

    country_idx = None
    for idx in range(1, hs_idx):
        if not _is_specific_country_cell(cells[idx]):
            continue
        numeric_tail = [
            cell
            for cell in cells[idx + 1 : hs_idx]
            if _is_numericish_cell(cell) or _is_loose_numeric_value_cell(cell)
        ]
        if len(numeric_tail) >= 2:
            country_idx = idx
            break
    if country_idx is None:
        return None

    description = _pick_structured_description(cells[1:country_idx])
    if not description or len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) < 4:
        return None

    numeric_tail = [
        cell
        for cell in cells[country_idx + 1 : hs_idx]
        if _is_numericish_cell(cell) or _is_loose_numeric_value_cell(cell)
    ]
    if len(numeric_tail) < 2:
        return None

    if len(numeric_tail) >= 3:
        quantity_hint = _parse_loose_number(numeric_tail[0])
        picked = _pick_quantity_cost_price(quantity_hint, numeric_tail)
    else:
        picked = _pick_sparse_quantity_cost_price(numeric_tail)
    if picked is None:
        return None

    quantity, cost, price = picked
    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": None,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": _normalized_country_value(cells[country_idx]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
        "_peer_hydrated": True,
    }


def _extract_compact_no_hs_item(cells: list[str], position: int | None) -> dict | None:
    if len(cells) < 6 or _is_terminal_hs_cell(cells[-1]):
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    if description_start >= len(cells) - 3:
        return None
    if any(_is_terminal_hs_cell(cell) for cell in cells[description_start + 1 :]):
        return None

    country_idx = None
    numeric_tail: list[str] = []
    search_end = min(len(cells) - 2, description_start + 4)
    for idx in range(description_start + 1, search_end + 1):
        country = str(cells[idx] or "").strip()
        if not _is_specific_country_cell(country):
            continue

        tail_candidate: list[str] = []
        for cell in cells[idx + 1 :]:
            if _is_numericish_cell(cell):
                tail_candidate.append(cell)
                continue
            if tail_candidate:
                break
            break

        if len(tail_candidate) >= 2:
            country_idx = idx
            numeric_tail = tail_candidate
            break

    if country_idx is None:
        return None

    description = _pick_structured_description(cells[description_start:country_idx])
    if not description:
        return None

    quantity = None
    cost = None
    price = None
    if len(numeric_tail) >= 3:
        quantity_hint = _parse_loose_number(numeric_tail[0])
        picked = _pick_quantity_cost_price(quantity_hint, numeric_tail)
        if picked is None:
            return None
        quantity, cost, price = picked
    else:
        cost = _parse_loose_number(numeric_tail[0])
        price = _parse_loose_number(numeric_tail[1])
        if cost is None or price is None or cost <= 0 or price <= 0:
            return None
        quantity = _infer_quantity_from_cost_and_total(cost, price)
        if quantity is None:
            return None

    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": None,
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": _normalized_country_value(cells[country_idx]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_zero_total_service_item(cells: list[str], position: int | None) -> dict | None:
    if position is None or len(cells) < 5 or any(_is_terminal_hs_cell(cell) for cell in cells[1:]):
        return None

    if len(cells) >= 2 and _is_article_like_cell(cells[1]):
        return None

    numeric_tail = [
        _parse_loose_number(cell)
        for cell in cells[-3:]
        if _parse_loose_number(cell) is not None
    ]
    if len(numeric_tail) < 3:
        return None

    quantity, cost, price = numeric_tail[-3:]
    if not (_is_reasonable_quantity(quantity) and _is_integerish_quantity(quantity)):
        return None
    if abs(cost) > 0.001 or abs(price) > 0.001:
        return None

    description = _pick_structured_description(cells[1:-3])
    if not description or len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) < 4:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": None,
        "quantity": float(round(quantity)),
        "unit": "pcs",
        "cost": 0.0,
        "price": 0.0,
        "country_origin": "Неизвестно",
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_sparse_no_hs_item_without_country(cells: list[str], position: int | None) -> dict | None:
    if len(cells) < 5 or any(_is_terminal_hs_cell(cell) for cell in cells[2:]):
        return None

    description_start = 2 if len(cells) >= 2 and _is_article_like_cell(cells[1]) else 1
    if description_start >= len(cells) - 2:
        return None

    numeric_start = len(cells)
    while numeric_start - 1 > description_start and _is_numericish_cell(cells[numeric_start - 1]):
        numeric_start -= 1

    numeric_tail = cells[numeric_start:]
    if len(numeric_tail) not in {2, 3}:
        return None
    if any(not _is_numericish_cell(cell) for cell in numeric_tail):
        return None

    description_cells = cells[description_start:numeric_start]
    if not description_cells:
        return None
    if any(
        _is_specific_country_cell(cell)
        and len(re.sub(r"[^A-Za-zА-Яа-яЁё]", "", str(cell or ""))) <= 4
        for cell in description_cells
    ):
        return None

    description = _pick_structured_description(description_cells)
    if not description or len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) < 4:
        return None

    if len(numeric_tail) == 3:
        quantity_hint = _parse_loose_number(numeric_tail[0])
        picked = _pick_quantity_cost_price(quantity_hint, numeric_tail)
    else:
        picked = _pick_sparse_quantity_cost_price(numeric_tail)
    if picked is None:
        return None

    quantity, cost, price = picked
    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": None,
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": "Неизвестно",
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _extract_loose_hs_tail_item(cells: list[str], position: int | None) -> dict | None:
    hs_idx = None
    for cell_idx in range(2, len(cells) - 3):
        if not _is_hs_like_cell(cells[cell_idx]):
            continue
        next_numish = sum(_is_numericish_cell(cell) for cell in cells[cell_idx + 1 : cell_idx + 6])
        prev_country = _is_specific_country_cell(cells[cell_idx - 1])
        if prev_country and next_numish >= 3:
            hs_idx = cell_idx
            break
    if hs_idx is None:
        for cell_idx in range(2, len(cells) - 3):
            if _is_hs_like_cell(cells[cell_idx]) or not _is_loose_hs_candidate(cells[cell_idx]):
                continue
            next_numish = sum(_is_numericish_cell(cell) for cell in cells[cell_idx + 1 : cell_idx + 6])
            prev_country = _is_specific_country_cell(cells[cell_idx - 1])
            if prev_country and next_numish >= 2:
                hs_idx = cell_idx
                break
    if hs_idx is None:
        return None

    declaration_idx = hs_idx - 2 if hs_idx >= 2 and _is_declaration_like_cell(cells[hs_idx - 2]) else None
    description_cells = cells[1 : declaration_idx if declaration_idx is not None else hs_idx - 1]
    description = " ".join(cell for cell in description_cells if cell).strip()
    if not description:
        return None

    tail = cells[hs_idx + 1 :]
    if len(tail) < 3:
        return None

    quantity_hint = _parse_loose_number(tail[0])
    picked = _pick_quantity_cost_price(quantity_hint, tail)
    if picked is None and re.search(r"\D", str(cells[hs_idx] or "")):
        numeric_tail = [_parse_loose_number(cell) for cell in tail if _parse_loose_number(cell) is not None]
        if len(numeric_tail) >= 2:
            trailing_cost = numeric_tail[-2]
            trailing_price = numeric_tail[-1]
            inferred_quantity = _infer_quantity_from_cost_and_total(trailing_cost, trailing_price)
            if inferred_quantity is not None and inferred_quantity >= 1 and trailing_price >= trailing_cost > 0:
                picked = (inferred_quantity, trailing_cost, trailing_price)
    if picked is None:
        return None

    quantity, cost, price = picked
    if quantity <= 0 or cost <= 0 or price <= 0:
        return None

    return {
        "position": position,
        "description": description,
        "hs_code": normalize_hs_code(cells[hs_idx]) or cells[hs_idx],
        "quantity": quantity,
        "unit": "pcs",
        "cost": cost,
        "price": price,
        "country_origin": _normalized_country_value(cells[hs_idx - 1]),
        "_decl_ref": _extract_declaration_ref(cells),
        "_line_sig": _build_structured_line_signature(cells),
    }


def _parse_item_from_cells(cells: list[str], position: int | None) -> dict | None:
    for extractor in (
        _extract_hs_last_item,
        _extract_sparse_hs_item_without_country,
        _extract_zero_total_service_item,
        _extract_sparse_no_hs_item_without_country,
        _extract_compact_no_hs_item,
        _extract_shifted_tail_item,
        _extract_hs_last_single_value_item,
        _extract_partial_hs_companion_item,
    ):
        item = extractor(cells, position)
        if item is not None:
            return item
    return None
