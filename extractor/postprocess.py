"""JSON repair, validation, and item-level postprocessing."""

import json
import re

from .preprocess import _is_table_item_line, _table_cells
from .prompts import _HEADER_FIELDS, _UNKNOWN_ORIGIN


def _repair_json(text: str) -> str:
    """
    Attempt to fix common JSON issues returned by LLMs:
    - trailing commas before } or ]
    - Python literals: True/False/None → true/false/null
    """
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    return text


def _is_numericish_cell(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"\d", value)) and bool(re.fullmatch(r"[\d\s,.'′/\-]+", value))


def _is_hs_like_cell(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 6 <= len(digits) <= 10


def _is_declaration_like_cell(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 10 <= len(digits) <= 14


def _is_country_like_cell(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", value)) and not _is_numericish_cell(value)


def _is_article_like_cell(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4,14}", str(value or "").strip()))


def _is_marker_like_cell(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return True
    if re.fullmatch(r"[+\-]", value):
        return True
    if _is_article_like_cell(value):
        return False
    return bool(re.fullmatch(r"[\d\s,./+\-]{1,8}", value))


def _parse_loose_number(value) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    text = text.replace("′", "'")
    text = re.sub(r"\s+", " ", text)

    # OCR often turns decimal separators into spaces or apostrophes.
    if re.fullmatch(r"\d+\s\d{2}", text):
        text = text.replace(" ", ".")
    elif re.fullmatch(r"\d+'\d{1,2}", text):
        text = text.replace("'", ".")

    text = text.replace(",", ".").replace(" ", "").replace("'", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _pick_cost_price_pair(quantity: float, tail_cells: list[str]) -> tuple[float, float] | None:
    """
    Pick the most plausible unit-cost/total pair from numeric tail cells.

    Pipe-table OCR often appends extra weight or marker cells after the real
    total, so using the last two numeric values is too brittle. Instead, scan
    all positive numeric cells after quantity and prefer the latest pair that
    best satisfies `quantity * cost ~= price`.
    """
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


def normalize_hs_code(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if 8 <= len(digits) <= 10:
        return digits
    return None


def filter_ocr_anomalies(items: list[dict]) -> list[dict]:
    """
    Remove only obvious OCR-corrupted rows and normalize HS codes.

    Conservative rules:
    - drop rows with non-positive position when position is present
    - normalize HS to digits; keep row if HS is missing after normalization
    - drop rows with non-positive quantity/cost/price
    - drop rows whose total is wildly inconsistent with quantity * unit cost
    """
    filtered: list[dict] = []

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

        normalized_hs = normalize_hs_code(out.get("hs_code"))
        out["hs_code"] = normalized_hs

        quantity = _parse_loose_number(out.get("quantity"))
        cost = _parse_loose_number(out.get("cost"))
        price = _parse_loose_number(out.get("price"))
        if quantity is None or cost is None or price is None:
            continue
        if quantity <= 0 or cost <= 0 or price <= 0:
            continue

        expected_total = quantity * cost
        if expected_total > 0:
            ratio = price / expected_total
            if ratio < 0.05 or ratio > 20:
                continue

        out["quantity"] = quantity
        out["cost"] = cost
        out["price"] = price
        filtered.append(out)

    return filtered


def extract_structured_pipe_items(cleaned_context: str) -> list[dict]:
    """
    Deterministically parse well-structured pipe-table OCR rows.

    This is a supplement to the LLM output, not a replacement. It is only
    reliable when OCR cleaning has already produced stable `| ... |` item rows.
    """
    if not cleaned_context:
        return []

    body = cleaned_context.split("=== INVOICE CONTENT ===\n", 1)[-1]
    parsed_items: list[dict] = []

    for line in body.splitlines():
        if not _is_table_item_line(line):
            continue

        cells = _table_cells(line)
        if len(cells) < 8:
            continue
        if len(cells) >= 2 and _is_marker_like_cell(cells[0]) and _is_article_like_cell(cells[1]):
            cells = cells[1:]
        if len(cells) < 8:
            continue

        hs_idx = None
        for idx in range(2, len(cells) - 3):
            if not _is_hs_like_cell(cells[idx]):
                continue
            next_numish = sum(_is_numericish_cell(cell) for cell in cells[idx + 1 : idx + 6])
            prev_country = _is_country_like_cell(cells[idx - 1])
            if prev_country and next_numish >= 3:
                hs_idx = idx
                break
        if hs_idx is None:
            continue

        position_digits = re.sub(r"\D", "", cells[0])
        if not position_digits:
            continue
        position = int(position_digits)
        if position <= 0:
            continue

        declaration_idx = (
            hs_idx - 2 if hs_idx >= 2 and _is_declaration_like_cell(cells[hs_idx - 2]) else None
        )
        description_cells = cells[1 : declaration_idx if declaration_idx is not None else hs_idx - 1]
        description = " ".join(cell for cell in description_cells if cell).strip()
        if not description:
            continue

        tail = cells[hs_idx + 1 :]
        if len(tail) < 3:
            continue

        quantity = _parse_loose_number(tail[0])
        if quantity is None:
            continue
        pair = _pick_cost_price_pair(quantity, tail)
        if pair is None:
            continue
        cost, price = pair
        if quantity <= 0 or cost <= 0 or price <= 0:
            continue

        parsed_items.append(
            {
                "position": position,
                "description": description,
                "hs_code": cells[hs_idx],
                "quantity": quantity,
                "unit": "pcs",
                "cost": cost,
                "price": price,
                "country_origin": cells[hs_idx - 1],
            }
        )

    return parsed_items


def post_fill_from_header(items: list[dict], header_meta: dict, currency_db: list[dict]) -> list[dict]:
    """
    Fill empty header-derived fields on every item from parsed document header.
    """
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


def spread_single_country_origin(items: list[dict]) -> list[dict]:
    """
    If every item with a known country_origin shares one value, copy it to
    items whose country_origin is missing/unknown.
    """
    known = {
        str(item.get("country_origin", "")).strip()
        for item in items
        if str(item.get("country_origin", "")).strip().lower() not in _UNKNOWN_ORIGIN
    }
    if len(known) != 1:
        return items

    single = next(iter(known))
    for item in items:
        val = str(item.get("country_origin", "")).strip()
        if val.lower() in _UNKNOWN_ORIGIN:
            item["country_origin"] = single
    return items


def deduplicate_items(items: list[dict]) -> list[dict]:
    """
    Remove cross-chunk duplicate rows without collapsing genuinely different
    rows that happen to share the same position number.
    """
    if not items:
        return items

    empty_values = {"", "null", "none"}

    def _is_empty(value) -> bool:
        return value is None or str(value).strip().lower() in empty_values

    def _is_cyrillic(text: str) -> bool:
        return bool(re.search(r"[А-Яа-яёЁ]", str(text or "")))

    def _norm_num(value, decimals: int = 2) -> float:
        try:
            return round(float(value or 0), decimals)
        except (TypeError, ValueError):
            return 0.0

    def _norm_hs(value) -> str | None:
        if _is_empty(value):
            return None
        return str(value).strip()

    def _make_key(item: dict) -> tuple | None:
        raw_pos = item.get("position")
        try:
            pos = int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            pos = None
        if pos is None:
            return None
        return (
            pos,
            _norm_hs(item.get("hs_code")),
            _norm_num(item.get("quantity"), 3),
            _norm_num(item.get("price")),
        )

    def _hs_conflict(a: dict, b: dict) -> bool:
        hs_a = _norm_hs(a.get("hs_code"))
        hs_b = _norm_hs(b.get("hs_code"))
        return hs_a is not None and hs_b is not None and hs_a != hs_b

    def _merge(base: dict, new: dict) -> dict:
        out = dict(base)
        if _is_cyrillic(new.get("description", "")) and not _is_cyrillic(out.get("description", "")):
            out["description"] = new["description"]
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
    result: list[dict] = []

    for item in items:
        key = _make_key(item)
        if key is None:
            result.append(item)
            continue
        if key in seen:
            existing_idx = seen[key]
            existing = result[existing_idx]
            if _hs_conflict(item, existing):
                result.append(item)
            else:
                result[existing_idx] = _merge(existing, item)
        else:
            seen[key] = len(result)
            result.append(item)

    return result


def sort_items_by_position(items: list[dict]) -> list[dict]:
    """
    Sort extracted rows by numeric position while preserving relative order for
    rows that share the same position or do not have a valid numeric position.
    """
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


def validate_and_parse(text: str) -> dict:
    """
    Parse and normalize JSON returned after chunked extraction.
    Supports list flattening and basic damaged-JSON recovery.
    """
    clean = re.sub(r"```json|```", "", text).strip()

    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if match:
        clean = match.group()

    parsed_data = []

    try:
        parsed_data = json.loads(clean)
    except json.JSONDecodeError:
        try:
            repaired = _repair_json(clean)
            parsed_data = json.loads(repaired)
        except json.JSONDecodeError:
            try:
                last_complete_item = repaired.rfind("}")
                if last_complete_item != -1:
                    fixed = repaired[: last_complete_item + 1] + "]"
                    parsed_data = json.loads(fixed)
            except Exception:
                parsed_data = []

    if isinstance(parsed_data, dict):
        parsed_data = parsed_data.get("items", parsed_data.get("extractions", [parsed_data]))

    if isinstance(parsed_data, list) and any(isinstance(item, list) for item in parsed_data):
        flattened = []
        for sublist in parsed_data:
            if isinstance(sublist, list):
                flattened.extend(sublist)
            else:
                flattened.append(sublist)
        parsed_data = flattened

    valid_items = []
    for item in parsed_data:
        if not isinstance(item, dict):
            continue

        description = item.get("description", "")
        if description and str(description).strip().lower() not in ("none", "null", ""):
            hs_code = str(item.get("hs_code", "")).strip().lower()
            if hs_code in ("none", "null", "", "0", "false"):
                item["hs_code"] = None

            for field in ["quantity", "cost", "price"]:
                try:
                    value = str(item.get(field, "0")).replace(",", ".")
                    item[field] = float(re.sub(r"[^\d.]", "", value) or 0)
                except (ValueError, TypeError):
                    item[field] = 0.0

            valid_items.append(item)

    if not valid_items:
        return {
            "data": {"items": [], "count": 0},
            "error": "No valid items extracted",
            "is_valid": 0,
        }
    return {
        "data": {"items": valid_items, "count": len(valid_items)},
        "error": "",
        "is_valid": 1,
    }
