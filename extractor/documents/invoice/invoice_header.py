from __future__ import annotations

import re


# Patterns to scan the FULL document text for global metadata that lives in
# the footer (e.g. "СТРАНА ПРОИСХОЖДЕНИЯ: КИТАЙ", "Код валюты: 840").
_FOOTER_PATTERNS: dict[str, re.Pattern] = {
    "country_origin": re.compile(
        r"страна\s+происхождения\s*:?\s*"
        r"([А-Яа-яёЁA-Za-z][А-Яа-яёЁA-Za-z-]*"
        r"(?:\s+(?!итого\b|total\b|сумма\b|всего\b|\d)"
        r"[А-Яа-яёЁA-Za-z][А-Яа-яёЁA-Za-z-]*){0,2})",
        re.IGNORECASE,
    ),
    "currency_code": re.compile(
        r"код\s+валюты\s*:?\s*(\d{3})",
        re.IGNORECASE,
    ),
    "currency_alpha": re.compile(
        r"(?:currency|total\s+amount|value)\s*(?:[:(]\s*|\s+)\b([A-Z]{3})\b\)?",
        re.IGNORECASE,
    ),
}

# ISO 4217 numeric → alpha-3 for the currencies most common in CIS trade docs.
_ISO4217_NUMERIC_TO_ALPHA3: dict[str, str] = {
    "840": "USD",
    "978": "EUR",
    "156": "CNY",
    "643": "RUB",
    "417": "KGS",
    "398": "KZT",
    "860": "UZS",
    "826": "GBP",
    "392": "JPY",
    "756": "CHF",
    "036": "AUD",
    "124": "CAD",
}

# Regex patterns to parse header metadata directly from OCR text.
_HEADER_PATTERNS = {
    "document_number": re.compile(
        r"(?:invoice[ \t]*(?:no\.?|num\.?|number|#|:)|№|накладн|счет)[ \t.:,]*([A-Z0-9\-/]{4,30})",
        re.IGNORECASE,
    ),
    "document_date": re.compile(
        r"(?:date|дата|от)\W*(\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4})",
        re.IGNORECASE,
    ),
    "country_sender": re.compile(
        r"\b(?:отправитель|shipper|страна\s+отправ\w*)\b\W*:?\s*([A-Za-zА-Яа-яёЁ ]{3,40})",
        re.IGNORECASE,
    ),
}

# Actual item rows must not be included in header context.
_ITEM_ROW_START_RE = re.compile(
    r"(?:"
    r"^\s*\d+[\s\t]+\S"
    r"|^\s*\|\s*\d+\s*\|"
    r")",
    re.MULTILINE,
)
_PRICE_RE = re.compile(r"\b\d+[.,]\d{2}\b")

# Table header rows are included, then extraction stops.
_TABLE_HEADER_RE = re.compile(
    r"\b(?:наименование|кол[-.\s]?во|количество|стоимость|ед[.\s]?изм"
    r"|unit\b|qty\b|quantity\b|amount\b|description\b|тн\s*вэд|hs\s*code"
    r"|product\b|item\b|total\b|value\b|price\b|count\b|rate\b)",
    re.IGNORECASE,
)


def extract_header(cleaned_text: str) -> str:
    """
    Extract document metadata header — includes table column headers but stops
    before the first invoice item data row.
    """
    lines = cleaned_text.split("\n")
    header_lines = []

    for line in lines:
        if not line.strip():
            continue
        if _ITEM_ROW_START_RE.match(line) and _PRICE_RE.search(line):
            break
        header_lines.append(line)
        if _TABLE_HEADER_RE.search(line):
            break
        if len(header_lines) >= 25:
            break

    if not header_lines:
        return ""
    return (
        "=== DOCUMENT HEADER (applies to ALL items in this invoice) ===\n"
        + "\n".join(header_lines)
    )


def parse_full_doc_metadata(context: str) -> dict:
    """
    Scan the FULL cleaned document text for global metadata that lives in the
    footer rather than the header.
    """
    meta: dict = {}
    for field, pattern in _FOOTER_PATTERNS.items():
        match = pattern.search(context)
        if not match:
            continue
        value = match.group(1).strip().rstrip(",;.")
        if not value:
            continue
        if field in {"currency_code", "currency_alpha"}:
            value = _ISO4217_NUMERIC_TO_ALPHA3.get(value, value)
            meta["currency_code"] = value
            continue
        meta[field] = value
    return meta


def parse_header_metadata(header_text: str) -> dict:
    """Extract key metadata from the header text using regex."""
    meta = {}
    for field, pattern in _HEADER_PATTERNS.items():
        match = pattern.search(header_text)
        if match:
            value = match.group(1).strip().rstrip(",;.")
            if value:
                meta[field] = value
    if "document_date" not in meta:
        match = re.search(r"\b(\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{4})\b", header_text)
        if match:
            meta["document_date"] = match.group(1)
    return meta


def build_header_metadata(context: str) -> tuple[str, dict]:
    header_context = extract_header(context)
    header_meta = parse_header_metadata(header_context)
    for key, value in parse_full_doc_metadata(context).items():
        if key not in header_meta:
            header_meta[key] = value
    return header_context, header_meta
