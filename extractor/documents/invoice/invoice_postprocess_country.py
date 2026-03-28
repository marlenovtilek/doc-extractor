from __future__ import annotations

import re

from ...normalizers.currency import resolve_country_code, resolve_country_from_numeric
from .invoice_cleaner import _parse_loose_number


UNKNOWN_ORIGIN = frozenset({"неизвестно", "unknown", "не указано", "null", "none", ""})
COUNTRY_NOISE_HINTS = (
    "order date",
    "please beware",
    "carry-over",
    "payment terms",
    "total amount",
    "value (eu)",
    "party",
    "invoice",
)
SERVICE_DESCRIPTION_HINTS = (
    "fracht",
    "freight",
    "shipping",
    "delivery",
    "transport",
    "handling",
    "service",
    "charge",
    "logistic",
    "достав",
    "перевоз",
    "фрахт",
    "услуг",
)

COUNTRY_CHAR_TRANSLATION = str.maketrans(
    {
        "Ι": "I",
        "İ": "I",
        "Ş": "S",
        "ş": "s",
        "Ь": "B",
        "В": "B",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
    }
)

COUNTRY_EDGE_NOISE_CHARS = frozenset({"I", "L", "X"})
COUNTRY_DIGIT_TRANSLATION = str.maketrans(
    {
        "0": "O",
        "1": "I",
        "3": "S",
        "5": "S",
        "8": "B",
    }
)


def _sanitize_country_origin(value):
    text = str(value or "").strip()
    if not text:
        return None

    lower = text.lower()
    if lower in UNKNOWN_ORIGIN or any(hint in lower for hint in COUNTRY_NOISE_HINTS):
        return None

    normalized_text = text.translate(COUNTRY_CHAR_TRANSLATION).strip()
    compact_alnum = re.sub(r"[^A-Za-z0-9]", "", normalized_text).upper()

    def _normalize_compact_code(raw_code: str) -> str | None:
        if not raw_code or len(raw_code) > 3:
            return None
        if resolve_country_code(raw_code) is not None:
            return raw_code
        translated = raw_code.translate(COUNTRY_DIGIT_TRANSLATION)
        if translated != raw_code and resolve_country_code(translated) is not None:
            return translated
        if len(raw_code) == 3:
            if raw_code[0] in COUNTRY_EDGE_NOISE_CHARS:
                candidate = raw_code[1:]
                if resolve_country_code(candidate) is not None:
                    return candidate
            if raw_code[-1] in COUNTRY_EDGE_NOISE_CHARS:
                candidate = raw_code[:2]
                if resolve_country_code(candidate) is not None:
                    return candidate
        return None

    if re.fullmatch(r"[A-Za-z]{2}(?:\s+[A-Za-z]{2})+", normalized_text):
        tokens = [token.upper() for token in re.findall(r"[A-Za-z]{2}", normalized_text)]
        valid_tokens = [token for token in tokens if resolve_country_code(token) is not None]
        if len(valid_tokens) == len(tokens) and len(set(valid_tokens)) == 1:
            return valid_tokens[0]
        return None

    if compact_alnum and len(compact_alnum) <= 3:
        normalized_code = _normalize_compact_code(compact_alnum)
        if normalized_code is not None:
            return normalized_code
        return None

    if re.search(r"[А-Яа-яЁё]", normalized_text):
        if resolve_country_code(normalized_text) is not None:
            return normalized_text
        return None

    if re.search(r"\d", normalized_text):
        return None

    words = re.findall(r"[A-Za-z]+", normalized_text)
    if len(words) > 1:
        return None
    if words and words[0].isupper() and len(words[0]) > 3 and resolve_country_code(words[0]) is None:
        return None

    return normalized_text or None


def _looks_like_service_charge_item(item: dict) -> bool:
    description = str(item.get("description") or "").strip()
    compact_description = re.sub(r"[^\wА-Яа-яЁё]", "", description)
    if len(compact_description) < 5:
        return False

    if str(item.get("hs_code") or "").strip():
        return False

    lower_description = description.lower()
    if any(hint in lower_description for hint in SERVICE_DESCRIPTION_HINTS):
        return True

    quantity = _parse_loose_number(item.get("quantity"))
    cost = _parse_loose_number(item.get("cost"))
    price = _parse_loose_number(item.get("price"))
    return (
        quantity is not None
        and quantity > 0
        and cost is not None
        and price is not None
        and abs(cost) <= 0.001
        and abs(price) <= 0.001
    )


def spread_single_country_origin(items: list[dict]) -> list[dict]:
    known = {
        str(item.get("country_origin", "")).strip()
        for item in items
        if str(item.get("country_origin", "")).strip().lower() not in UNKNOWN_ORIGIN
    }
    if len(known) != 1:
        return items

    single = next(iter(known))
    for item in items:
        val = str(item.get("country_origin", "")).strip()
        if val.lower() in UNKNOWN_ORIGIN and not _looks_like_service_charge_item(item):
            item["country_origin"] = single
    return items


def fill_derived_item_fields(items: list[dict]) -> list[dict]:
    for item in items:
        item["country_origin"] = _sanitize_country_origin(item.get("country_origin"))
        if item["country_origin"] is None:
            resolved_origin = resolve_country_from_numeric(item.get("country_origin_code"))
            if resolved_origin is not None:
                item["country_origin"] = resolved_origin

        cost = item.get("cost")
        is_empty_cost = cost is None or str(cost).strip().lower() in ("", "null", "none", "0")
        if is_empty_cost:
            try:
                price = float(item.get("price") or 0)
                qty = float(item.get("quantity") or 1)
                if price > 0 and qty > 0:
                    item["cost"] = round(price / qty, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        unit = item.get("unit")
        if unit is None or str(unit).strip().lower() in ("", "null", "none"):
            item["unit"] = "pcs"
    return items


def reconcile_numeric_fields(items: list[dict]) -> list[dict]:
    for item in items:
        quantity = _parse_loose_number(item.get("quantity"))
        cost = _parse_loose_number(item.get("cost"))
        price = _parse_loose_number(item.get("price"))
        if quantity is None or cost is None or price is None:
            continue
        if quantity <= 0 or cost <= 0 or price <= 0:
            continue

        expected_total = quantity * cost
        if expected_total <= 0:
            continue

        rel_err = abs(expected_total - price) / max(expected_total, price, 1.0)
        if rel_err <= 0.05:
            continue

        inferred_qty = price / cost
        rounded_qty = round(inferred_qty)
        if not (1 <= rounded_qty <= 1000):
            continue
        if abs(inferred_qty - rounded_qty) > 0.12:
            continue
        if abs(price - (rounded_qty * cost)) > max(1.0, 0.03 * price):
            continue

        item["quantity"] = float(rounded_qty)
    return items
