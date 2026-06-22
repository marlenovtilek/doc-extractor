import re
from typing import Any


_POSITION_RE = re.compile(r"^\s*(\d{1,4})(?:[.)]|(?:\s+))")
_DIGIT_TOKEN_RE = re.compile(r"^[\d.,]+$")
_HS_CODE_RE = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")
_DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
_DATE_RU_RE = re.compile(
    r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}\b",
    re.IGNORECASE,
)
_DOC_NUMBER_RE = re.compile(
    r"(?:invoice|инвойс|счет[- ]?фактура|счет)\D{0,30}(?:№|no\.?|n[oо]\.?)\s*([A-Za-z0-9./_-]{3,})",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"\b(USD|EUR|RUB|CNY|KZT|KGS|GBP|AED|TRY)\b", re.IGNORECASE)

_TOTAL_MARKERS = (
    "итого",
    "subtotal",
    "grand total",
    "total amount",
    "total",
    "резюме",
    "summary",
    "общее число единиц",
    "total units",
)

_HEADER_MARKERS = (
    "описан",
    "description",
    "код тн",
    "hs code",
    "код",
    "страна происх",
    "country of origin",
    "цена",
    "amount",
    "quantity",
    "кол-во",
    "qty",
)

_UNIT_MAP = {
    "шт": "шт",
    "шт.": "шт",
    "pcs": "pcs",
    "pc": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "kg": "kg",
    "кг": "кг",
    "set": "set",
    "sets": "set",
    "box": "box",
    "boxes": "box",
    "уп": "уп",
    "уп.": "уп",
    "упак": "упак",
}

_COUNTRY_BY_CODE = {
    "CN": "China",
    "DE": "Germany",
    "RU": "Russia",
    "KZ": "Kazakhstan",
    "KG": "Kyrgyzstan",
    "AE": "UAE",
    "US": "USA",
    "IT": "Italy",
    "TR": "Turkey",
    "KR": "Korea",
    "JP": "Japan",
    "IN": "India",
    "PL": "Poland",
    "CZ": "Czech Republic",
}

_COUNTRY_ALIASES = {
    "китай": ("China", "CN"),
    "china": ("China", "CN"),
    "германия": ("Germany", "DE"),
    "germany": ("Germany", "DE"),
    "россия": ("Russia", "RU"),
    "russia": ("Russia", "RU"),
    "казахстан": ("Kazakhstan", "KZ"),
    "kazakhstan": ("Kazakhstan", "KZ"),
    "кыргызстан": ("Kyrgyzstan", "KG"),
    "kyrgyzstan": ("Kyrgyzstan", "KG"),
    "оаэ": ("UAE", "AE"),
    "uae": ("UAE", "AE"),
    "usa": ("USA", "US"),
    "сша": ("USA", "US"),
    "италия": ("Italy", "IT"),
    "italy": ("Italy", "IT"),
    "турция": ("Turkey", "TR"),
    "turkey": ("Turkey", "TR"),
    "корея": ("Korea", "KR"),
    "korea": ("Korea", "KR"),
    "япония": ("Japan", "JP"),
    "japan": ("Japan", "JP"),
    "индия": ("India", "IN"),
    "india": ("India", "IN"),
}

_CURRENCY_NAMES = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "RUB": "Russian Ruble",
    "CNY": "Chinese Yuan",
    "KZT": "Kazakhstani Tenge",
    "KGS": "Kyrgyzstani Som",
    "GBP": "British Pound",
    "AED": "UAE Dirham",
    "TRY": "Turkish Lira",
}


def extract_scan_table_invoice(ocr_text: str) -> dict[str, Any]:
    lines = _clean_lines(ocr_text)
    if not lines:
        return {"items": [], "count": 0, "looks_like_scan_table": False}

    if not _looks_like_scan_table(lines):
        return {"items": [], "count": 0, "looks_like_scan_table": False}

    header_fields = _extract_header_fields(lines)
    row_blocks = _collect_row_blocks(lines)
    items = []

    for row_parts in row_blocks:
        parsed = _parse_row(row_parts, header_fields)
        if parsed is not None:
            items.append(parsed)

    return {
        "items": items,
        "count": len(items),
        "looks_like_scan_table": bool(items),
    }


def _clean_lines(text: str) -> list[str]:
    if not text:
        return []

    lines: list[str] = []
    for raw_line in str(text).replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line.replace("\xa0", " ")).strip()
        if line:
            lines.append(line)
    return lines


def _looks_like_scan_table(lines: list[str]) -> bool:
    lower_lines = [line.lower() for line in lines]
    position_lines = [line for line in lines if _POSITION_RE.match(line)]
    numeric_tail_hits = sum(1 for line in lines if _line_has_numeric_tail(line))
    header_hits = any(marker in line for line in lower_lines for marker in _HEADER_MARKERS)

    if len(position_lines) >= 5 and numeric_tail_hits >= 3:
        return True
    if len(position_lines) >= 2 and numeric_tail_hits >= 2 and header_hits:
        return True
    return False


def _line_has_numeric_tail(line: str) -> bool:
    tokens = line.split()
    digitish = 0
    for token in reversed(tokens):
        if _DIGIT_TOKEN_RE.match(token):
            digitish += 1
            if digitish >= 2:
                return True
        elif digitish:
            break
    return False


def _collect_row_blocks(lines: list[str]) -> list[list[str]]:
    row_blocks: list[list[str]] = []
    current: list[str] = []
    stopped = False

    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in _TOTAL_MARKERS):
            if current:
                row_blocks.append(current)
                current = []
            stopped = True
            break

        if _POSITION_RE.match(line):
            if current:
                row_blocks.append(current)
            current = [line]
            continue

        if current and not _looks_like_header_only_line(lowered):
            current.append(line)

    if current and not stopped:
        row_blocks.append(current)

    return row_blocks


def _looks_like_header_only_line(lowered: str) -> bool:
    return any(marker in lowered for marker in _HEADER_MARKERS) and not _line_has_numeric_tail(lowered)


def _extract_header_fields(lines: list[str]) -> dict[str, Any]:
    header_text = "\n".join(lines[:60])

    document_number = None
    match_number = _DOC_NUMBER_RE.search(header_text)
    if match_number:
        document_number = match_number.group(1).strip()

    document_date = None
    match_date = _DATE_RE.search(header_text) or _DATE_RU_RE.search(header_text)
    if match_date:
        document_date = match_date.group(0).strip()

    currency_code = None
    currency_name = None
    match_currency = _CURRENCY_RE.search(header_text)
    if match_currency:
        currency_code = match_currency.group(1).upper()
        currency_name = _CURRENCY_NAMES.get(currency_code)

    country_sender = None
    lowered = header_text.lower()
    for alias, (name, _) in _COUNTRY_ALIASES.items():
        if alias in lowered:
            country_sender = name
            break

    return {
        "document_number": document_number,
        "document_date": document_date,
        "currency_code": currency_code,
        "currency_name": currency_name,
        "country_sender": country_sender,
    }


def _parse_row(row_parts: list[str], header_fields: dict[str, Any]) -> dict[str, Any] | None:
    row_text = " ".join(part.strip() for part in row_parts if part.strip())
    match = _POSITION_RE.match(row_text)
    if not match:
        return None

    position = int(match.group(1))
    body = row_text[match.end():].strip()
    if not body:
        return None

    country_origin, country_origin_code = _extract_country(body)

    hs_matches = _HS_CODE_RE.findall(body)
    hs_code = hs_matches[-1] if hs_matches else None

    tokens = body.split()
    working = tokens[:]

    cost = None
    cost_start = None
    cost, cost_start = _consume_number_from_tail(working, max_value=1_000_000_000)
    if cost_start is not None:
        del working[cost_start:]

    price = None
    price_start = None
    price, price_start = _consume_number_from_tail(working, max_value=1_000_000_000)
    if price_start is not None:
        del working[price_start:]

    unit = None
    if working:
        unit = _normalize_unit(working[-1])
        if unit is not None:
            working.pop()

    quantity = None
    quantity_start = None
    quantity, quantity_start = _consume_number_from_tail(working, max_value=1_000_000)
    if quantity_start is not None:
        del working[quantity_start:]

    description = " ".join(working).strip(" -|,.;:")
    if hs_code:
        description = re.sub(rf"(?<!\d){re.escape(hs_code)}(?!\d)", " ", description)
    if country_origin_code:
        description = re.sub(rf"\b{re.escape(country_origin_code)}\b", " ", description, flags=re.IGNORECASE)
    if country_origin:
        description = re.sub(re.escape(country_origin), " ", description, flags=re.IGNORECASE)
    description = re.sub(r"\s+", " ", description).strip(" -|,.;:")

    if not description:
        description = re.sub(r"\s+", " ", body).strip(" -|,.;:")

    item = {
        "position": position,
        "description": description or None,
        "quantity": quantity,
        "unit": unit,
        "cost": cost,
        "price": price,
        "hs_code": hs_code,
        "country_origin": country_origin,
        "country_origin_code": country_origin_code,
    }
    item.update(header_fields)
    return item if item.get("description") else None


def _consume_number_from_tail(tokens: list[str], *, max_value: float) -> tuple[int | float | None, int | None]:
    if not tokens:
        return None, None

    end = len(tokens) - 1
    while end >= 0:
        token = tokens[end].strip("()[]{};,")
        if _DIGIT_TOKEN_RE.match(token):
            break
        end -= 1

    if end < 0:
        return None, None

    for span_len in (3, 2, 1):
        start = end - span_len + 1
        if start < 0:
            continue
        parts = [tokens[idx].strip("()[]{};,") for idx in range(start, end + 1)]
        if not _is_number_span(parts):
            continue
        parsed = _parse_number("".join(parts))
        if parsed is None:
            continue
        if abs(float(parsed)) > max_value:
            continue
        return parsed, start

    return None, None


def _is_number_span(parts: list[str]) -> bool:
    if not parts or not all(_DIGIT_TOKEN_RE.match(part) for part in parts):
        return False

    if len(parts) == 1:
        return True

    if any("," in part or "." in part for part in parts):
        return True

    if not parts[0].isdigit() or len(parts[0]) > 3:
        return False

    return all(part.isdigit() and len(part) == 3 for part in parts[1:])


def _parse_number(text: str) -> int | float | None:
    normalized = re.sub(r"[^\d,.-]", "", text or "")
    if not normalized or not re.search(r"\d", normalized):
        return None

    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        if normalized.count(",") == 1 and len(normalized.split(",")[-1]) in (1, 2):
            normalized = normalized.replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "." in normalized:
        if normalized.count(".") != 1 or len(normalized.split(".")[-1]) not in (1, 2):
            normalized = normalized.replace(".", "")

    try:
        value = float(normalized)
    except ValueError:
        return None

    if value.is_integer():
        return int(value)
    return value


def _normalize_unit(token: str) -> str | None:
    return _UNIT_MAP.get(token.strip().lower())


def _extract_country(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    for alias, (name, code) in _COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return name, code

    for token in text.split():
        upper = token.strip("()[]{};,.").upper()
        if upper in _COUNTRY_BY_CODE:
            return _COUNTRY_BY_CODE[upper], upper

    return None, None
