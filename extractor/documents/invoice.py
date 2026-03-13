from __future__ import annotations

import html
import json
import re
import time
from collections import Counter
from datetime import datetime
from typing import Any

import langextract as lx

from .base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ..currency import build_currency_db_string, finalize_items, load_currency_db
from ..metrics import RunMetrics, compute_field_fill_rates, merge_token_usage, timer
from ..providers import (
    ModelTarget,
    extract_with_langextract_entities,
    extract_with_langextract_optimized,
    resolve_model_target,
)


# JSON Schema that the Cerebras API enforces on the model's output.
# Using an {"items": [...]} wrapper because json_schema mode requires an
# object at the root (not a bare array).
# validate_and_parse() already handles the {"items": [...]} dict unwrap.
_CEREBRAS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": ["integer", "null"]},
                    "description": {"type": "string"},
                    "hs_code": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "cost": {"type": ["number", "null"]},
                    "price": {"type": ["number", "null"]},
                    "currency_code": {"type": ["string", "null"]},
                    "currency_name": {"type": ["string", "null"]},
                    "document_date": {"type": ["string", "null"]},
                    "document_number": {"type": ["string", "null"]},
                    "country_origin": {"type": "string"},
                    "country_origin_code": {"type": ["integer", "null"]},
                    "country_sender": {"type": ["string", "null"]},
                },
                "required": ["description"],
            },
        }
    },
    "required": ["items"],
}

_CEREBRAS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "invoice_items",
        "schema": _CEREBRAS_ITEM_SCHEMA,
    },
}


EXTRACTION_PROMPT = """
# ROLE
You are a specialized agent for high-precision extraction of customs invoice data (TN VED/EAEU standards). Your goal is to produce a JSON output that mirrors the document content with 100% fidelity.
# CORE EXTRACTION LOGIC
1. **Language Priority**:
   - Primary: Russian (RU).
   - If a line item has both RU and EN descriptions, extract ONLY the Russian text.
   - If only one language is present (RU or EN), extract it exactly as is.
   - DO NOT translate. DO NOT truncate. Capture full technical strings.
2. **HS Codes (ТН ВЭД) Handling**:
   - **Verbatim Extraction**: Copy digits exactly. No spaces, no dots.
   - **Length Priority**: If you find two versions of a code for one item (e.g., 6-digit and 10-digit), ALWAYS pick the longest one.
   - **No Modification**: Never add or remove digits. If the code is 4, 6, 8, or 10 digits, keep it as is.
3. **Data Integrity**:
   - Extract every single row that has a price.
   - Do not merge similar rows. Do not skip any items.
# FIELD SPECIFICATIONS
- `position`: Integer row number from the № / POS / п/п column. Must be unique per invoice line. If missing, use null.
- `description`: Full Russian name (priority) or English name. No summarization.
- `hs_code`: String of digits. Verbatim copy.
- `unit`: Standardize to: kg, pcs, l, set, m. (Default to "pcs" if missing).
- `quantity`: Numeric value (use "." decimal separator).
- `cost`: Price per unit. If not explicit, calculate: `price` / `quantity`.
- `price`: Total row price.
- `country_origin`: 2-letter ISO code (DE, NL, CN, RU). If missing, use "Неизвестно".
- `country_origin_code`: Numeric ISO country code (e.g., 276 for DE, 156 for CN). If missing, use null.
- `currency_code`: 3-letter ISO code from DOCUMENT HEADER in `additional_context` (e.g., "USD", "EUR").
- `currency_name`: Full currency name from DOCUMENT HEADER in `additional_context` (e.g., "US Dollar", "Euro").
# GLOBAL DOCUMENT CONTEXT
From the `additional_context` (DOCUMENT HEADER), you MUST apply these values to EVERY item in the JSON array:
- `document_number`
- `document_date`
- `country_sender`
- `currency_code`
- `currency_name`
# OUTPUT FORMATTING
- Return ONLY a raw JSON array of objects.
- Do not include markdown code blocks (```json).
- No preamble, no post-text, no explanations.
- Start with `[` and end with `]`.
"""

EXTRACTION_PROMPT_GPT_OSS = """
ROLE:
You are a deterministic customs invoice line-item extractor.
TASK:
Extract ALL line items from the provided invoice text.
EXTRACTION RULES:
1. POSITION
   - Read the row number from the № / POS / п/п / No. column and output it as "position" (integer).
   - Each invoice line has a unique position. Two rows with identical data but different position numbers are genuinely different line items — DO NOT skip either.
   - If no position column is present, output null.
2. LANGUAGE PRIORITY
   - Prefer Russian descriptions.
   - If the document contains both Russian and English sections for the same item, extract ONLY the Russian description.
   - If the document is monolingual, preserve the original language exactly as written.
3. HS CODE
   - Copy exactly as written.
   - Do NOT truncate.
   - Do NOT normalize.
   - Do NOT add digits.
   - If multiple HS codes exist for one item, select the longest one.
4. HEADER DATA (GLOBAL CONTEXT)
   The "=== DOCUMENT HEADER ===" block at the top of the document contains header-level data.
   The following fields MUST be copied to EVERY extracted item:
   - document_number
   - document_date
   - country_sender
   - currency_code
   - currency_name
5. COST / PRICE FIELD MAPPING
   - "cost"  = unit price (price per single item) — maps to columns named "unit_price", "Unit Price", "Preis/Einheit", etc.
   - "price" = total line price (quantity × unit price) — maps to columns named "total_price", "Total", "Gesamtpreis", "Стоимость", etc.
   - If "cost" is missing but "price" and "quantity" are present: cost = price / quantity.
   - If calculation is impossible, use null. Do NOT guess.
6. UNIT NORMALIZATION
   - If unit is missing, default to "pcs".
   - Allowed values ONLY:
     kg, pcs, l, set, m
   - Normalize variations (e.g., "шт." → "pcs", "кг" → "kg").
7. COUNTRY OF ORIGIN
   - country_origin must be a 2-letter ISO code (e.g., DE, CN, RU).
   - If unknown, use "Неизвестно".
   - country_origin_code must be the numeric ISO country code.
   - If unknown, use null.
   - Do NOT invent country data.
OUTPUT:
Return a JSON object: {"items": [...]}.
The "items" array contains one object per invoice line item.
No markdown, no explanation, no preamble.
If no items found, return {"items": []}.
"""

# Few-shot examples that teach LangExtract the schema shape.
#
# Example 1 — BILINGUAL invoice (RU + EN sections).
#   Rule: prefer Russian description; prefer the LONGER hs_code (RU section
#   often has 10-digit, EN section 8-digit — but length varies per document).
#
# Example 2 — MONOLINGUAL ENGLISH invoice.
#   Rule: keep English description as-is; hs_code may be any valid length
#   (4, 6, 8, or 10 digits) — copy verbatim, never truncate or extend.
EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "=== CURRENCY DATABASE (REFERENCE) ===\n"
            '[{"code":"EUR","name":"Euro"}]\n\n'
            "=== INVOICE CONTENT ===\n"
            "Коммерческий инвойс № INV-001  Дата: 10/01/2025\n"
            "Грузоотправитель: Acme GmbH, Germany\n\n"
            "--- SECTION RU ---\n"
            "| № | Наименование товара | Кол-во | Цена за ед. | Стоимость |\n"
            "| 1 | Ноутбук Dell XPS код ТНВЭД 8471309900 | 2 шт. | 850,00 | 1700,00 |\n\n"
            "--- SECTION EN (CUSTOMS INVOICE) ---\n"
            "| Material No. | Description | Co. of Origin | Customs tariff | Qty | Unit price | Value |\n"
            "| 12345 | Dell XPS Laptop | DE | 84713099 | 2,00 | 850,00 | 1700,00 |\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="invoice_item",
                extraction_text="Ноутбук Dell XPS",
                attributes={
                    "position": 1,
                    "hs_code": "8471309900",
                    "description": "Ноутбук Dell XPS",
                    "quantity": 2,
                    "unit": "pcs",
                    "cost": 850.00,
                    "price": 1700.00,
                    "currency_code": "EUR",
                    "currency_name": "Euro",
                    "document_date": "10/01/2025",
                    "document_number": "INV-001",
                    "country_origin": "DE",
                    "country_origin_code": 276,
                    "country_sender": "Germany",
                },
            )
        ],
    ),
    lx.data.ExampleData(
        text=(
            "=== CURRENCY DATABASE (REFERENCE) ===\n"
            '[{"code":"USD","name":"US Dollar"}]\n\n'
            "=== INVOICE CONTENT ===\n"
            "Commercial Invoice No. CI-2024-089  Date: 05/03/2024\n"
            "Shipper: TechParts Inc., United States\n\n"
            "No. | Description            | HS Code  | Qty | Unit price | Total\n"
            "1   | Industrial servo motor | 85016100 |  5  | 125.00     | 625.00\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="invoice_item",
                extraction_text="Industrial servo motor",
                attributes={
                    "position": 1,
                    "hs_code": "85016100",
                    "description": "Industrial servo motor",
                    "quantity": 5,
                    "unit": "pcs",
                    "cost": 125.00,
                    "price": 625.00,
                    "currency_code": "USD",
                    "currency_name": "US Dollar",
                    "document_date": "05/03/2024",
                    "document_number": "CI-2024-089",
                    "country_origin": "Неизвестно",
                    "country_origin_code": None,
                    "country_sender": "United States",
                },
            )
        ],
    ),
]


# Fields that must be propagated from the header to all items.
_HEADER_FIELDS = (
    "document_date",
    "document_number",
    "country_sender",
    "currency_code",
    "currency_name",
    "country_origin",
)

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
        r"(?:invoice[ \t]*(?:no\.?|num\.?|#|:)|№|накладн|счет)[ \t.:,]*([A-Z0-9\-/]{4,30})",
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

_UNKNOWN_ORIGIN = frozenset({"неизвестно", "unknown", "не указано", "null", "none", ""})


_STRUCTURE_HINTS = (
    "invoice",
    "commercial invoice",
    "счет-фактура",
    "инвойс",
    "packing list",
    "упаковочный лист",
    "shipment",
    "exporter",
    "consignee",
    "customer",
    "currency",
    "валюта",
    "country",
    "страна",
    "port",
    "поставщик",
    "грузополучатель",
    "итого",
    "total amount",
    "summary",
    "payment terms",
)

_TABLE_HEADER_HINTS = (
    "description",
    "описание",
    "part",
    "артикул",
    "origin",
    "происх",
    "hs",
    "тн вэд",
    "code",
    "код",
    "qty",
    "кол-",
    "price",
    "цена",
    "total",
    "сумма",
    "weight",
    "вес",
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
        if field == "currency_code":
            value = _ISO4217_NUMERIC_TO_ALPHA3.get(value, value)
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
    return meta


def _normalize_pipe_table(text: str) -> str:
    """
    Normalize OCR invoice text before chunking and LLM extraction.

    Fixes single-line Markdown tables and removes separator rows that make
    models stop at the first page boundary.
    """
    # Common row starts in OCR dumps:
    #   | 1 | Description |
    #   | 70 | 507354 | MAT 153 ... |
    #   | 506992 | XSW 1-ME3-GB | ...
    # We split before rows, but avoid price cells by requiring either:
    #   - a description cell starting with a letter, or
    #   - an article cell (4-14 digits) followed by a description cell.
    text = re.sub(
        r"(?<!\n)(?="
        r"\|[ \t]*(?:\d{1,4}|[+\-])[ \t]*\|[ \t]*"
        r"(?:"
        r"[А-Яа-яёЁA-Za-z]"
        r"|"
        r"\d{4,14}[ \t]*\|[ \t]*[А-Яа-яёЁA-Za-z]"
        r")"
        r")",
        "\n",
        text,
    )
    text = re.sub(r"[ \t]*\|[- \t|]+\|[ \t]*$", "|", text, flags=re.MULTILINE)
    text = re.sub(r"^[|\- \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", "\n", text)

    dense_lines = []
    row_start_re = re.compile(
        r"\|[ \t]*(?:\d{1,8}|[+\-])[ \t]*\|[ \t]*"
        r"(?:\d{4,14}[ \t]*\|[ \t]*)?[А-Яа-яёЁA-Za-z]"
    )
    for line in text.split("\n"):
        starts = []
        for match in row_start_re.finditer(line):
            if starts and match.start() - starts[-1] < 20:
                continue
            starts.append(match.start())
        if len(starts) <= 1:
            dense_lines.append(line)
            continue

        starts.append(len(line))
        for start, end in zip(starts, starts[1:]):
            part = line[start:end].strip()
            if part:
                dense_lines.append(part)

    return "\n".join(dense_lines)


def _strip_markup_noise(text: str) -> str:
    """
    Remove OCR-export markup that confuses row detection:
    - markdown image markers
    - HTML table tags
    - inline formatting tags
    - markdown bold markers
    """
    text = html.unescape(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)</?(td|th)\b[^>]*>", " | ", text)
    text = re.sub(r"(?i)</?(tr|table|tbody|thead|p|div|span)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", "")
    return text


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("|") if cell.strip()]


def _is_pipe_table_line(line: str) -> bool:
    return line.count("|") >= 4


def _is_table_header_line(line: str) -> bool:
    if not _is_pipe_table_line(line):
        return False
    lower = line.lower()
    return sum(token in lower for token in _TABLE_HEADER_HINTS) >= 2


def _is_table_item_line(line: str) -> bool:
    if not _is_pipe_table_line(line):
        return False

    cells = _table_cells(line)
    has_price = bool(_PRICE_RE.search(line))
    has_textual_payload = any(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell) for cell in cells[1:4])

    row_start = re.match(r"^\|\s*(\d{1,8}|[+\-])\s*\|", line)
    if row_start:
        if row_start.group(1).isdigit():
            return len(cells) >= 6 and has_price and has_textual_payload
        has_article = any(re.fullmatch(r"\d{4,14}", cell) for cell in cells[1:3])
        return len(cells) >= 6 and has_article and has_price and has_textual_payload

    if len(cells) < 5:
        return False
    has_article = any(re.fullmatch(r"\d{4,14}", cell) for cell in cells[:3])
    return has_article and has_price and has_textual_payload


def _looks_like_article_cell(cell: str) -> bool:
    return bool(re.fullmatch(r"\d{4,14}", cell.strip()))


def _looks_like_marker_cell(cell: str) -> bool:
    cell = cell.strip()
    if not cell:
        return True
    if re.fullmatch(r"[+\-]", cell):
        return True
    if re.fullmatch(r"\d{1,3}", cell):
        return True
    if _looks_like_article_cell(cell):
        return False
    return bool(re.fullmatch(r"[\d\s,./+\-]{1,8}", cell))


def _looks_like_boilerplate_line(line: str) -> bool:
    lower = line.lower()
    return any(token in lower for token in _STRUCTURE_HINTS)


def _boilerplate_key(line: str) -> str:
    lower = line.lower()
    lower = re.sub(r"\d", "0", lower)
    lower = re.sub(r"\s+", " ", lower)
    return lower.strip()


def _looks_like_pipe_noise(line: str) -> bool:
    if _is_table_header_line(line) or _is_table_item_line(line):
        return False

    cells = _table_cells(line)
    meaningful_cells = sum(
        bool(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell)) or bool(re.search(r"\d{4,}", cell))
        for cell in cells
    )
    short_cells = sum(len(cell) <= 2 for cell in cells)

    if len(cells) >= 6 and meaningful_cells < 3:
        return True
    if len(line) > 300:
        return True
    if len(line) > 220 and meaningful_cells < 4:
        return True
    if len(cells) >= 8 and short_cells >= len(cells) - 2:
        return True
    if not _PRICE_RE.search(line) and meaningful_cells < 5 and short_cells >= max(4, len(cells) // 2):
        return True
    return False


def _looks_like_blob_noise(line: str) -> bool:
    if _looks_like_boilerplate_line(line):
        return False
    if "|" in line:
        return False

    tokens = re.findall(r"\w+", line.lower())
    if not tokens:
        return False

    top_token_count = Counter(tokens).most_common(1)[0][1]
    digit_count = sum(ch.isdigit() for ch in line)
    repeated_fragment = top_token_count >= 8
    numeric_heavy = digit_count >= 30
    if repeated_fragment and len(line) >= 60:
        return True
    return numeric_heavy and len(line) >= 120


def _trim_item_line(line: str) -> str:
    """
    Keep the leading cells of oversized OCR table rows.

    Noisy exports sometimes glue the next row or page boilerplate onto the end
    of an otherwise valid item row. Most invoice variants in this service fit
    within ~12 meaningful columns, so trimming the tail is safer than leaving a
    multi-row blob intact.
    """
    cells = _table_cells(line)
    if len(cells) <= 11:
        return line

    max_cells = min(len(cells), 12)
    tail_candidate = cells[max_cells - 1]
    tail_looks_noisy = (
        len(tail_candidate) > 80
        or len(re.findall(r"\d+[.,]\d+", tail_candidate)) >= 3
        or len(re.findall(r"\d{4,14}", tail_candidate)) >= 2
    )
    if tail_looks_noisy:
        max_cells = 11
    elif len(cells) <= 12:
        return line

    return "| " + " | ".join(cells[:max_cells]) + " |"


def _normalize_item_schema(lines: list[str]) -> list[str]:
    """
    In OCR dumps with mixed schemas, normalize continuation/index columns away
    when the table is mostly article-led.

    Example:
      | + | 507115 | XSW 1-835-A | ... |
      | 70 | 507354 | MAT 153 ... | ... |
    becomes:
      | 507115 | XSW 1-835-A | ... |
      | 507354 | MAT 153 ... | ... |
    """
    item_lines = [line for line in lines if _is_table_item_line(line)]
    if not item_lines:
        return lines

    article_leading = 0
    marker_prefixed = 0
    for line in item_lines:
        cells = _table_cells(line)
        if not cells:
            continue
        if _looks_like_article_cell(cells[0]):
            article_leading += 1
        elif len(cells) >= 2 and _looks_like_marker_cell(cells[0]) and _looks_like_article_cell(cells[1]):
            marker_prefixed += 1

    if article_leading < 5 or marker_prefixed < 1:
        return lines

    normalized = []
    for line in lines:
        if not _is_table_item_line(line):
            normalized.append(line)
            continue

        cells = _table_cells(line)
        if len(cells) >= 2 and _looks_like_marker_cell(cells[0]) and _looks_like_article_cell(cells[1]):
            line = "| " + " | ".join(cells[1:]) + " |"
        normalized.append(_trim_item_line(line))

    return normalized


def _compact_table_ocr(lines: list[str]) -> list[str]:
    """
    For OCR dumps that are clearly pipe-table based, keep:
    - document metadata / totals lines
    - real table headers
    - real table item rows
    while suppressing repeated per-page boilerplate and large garbage blobs.
    """
    compacted = []
    seen_boilerplate = set()

    for line in lines:
        if _is_pipe_table_line(line):
            if _looks_like_pipe_noise(line):
                continue
            if _is_table_item_line(line):
                line = _trim_item_line(line)
            compacted.append(line)
            continue

        if _looks_like_blob_noise(line):
            continue

        if _looks_like_boilerplate_line(line):
            key = _boilerplate_key(line)
            if key in seen_boilerplate:
                continue
            seen_boilerplate.add(key)

        compacted.append(line)

    return _normalize_item_schema(compacted)


def clean_text(raw_text: str, currency_db_str: str) -> str:
    """Clean OCR text and prepend the currency database block."""
    if not raw_text:
        return ""

    text = raw_text.replace("\r", "")
    text = _strip_markup_noise(text)
    text = _normalize_pipe_table(text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = []
    for line in text.split("\n"):
        clean_line = re.sub(r"[ \t]+", " ", line).strip()
        if clean_line:
            lines.append(clean_line)

    if sum(_is_pipe_table_line(line) for line in lines) >= 8:
        lines = _compact_table_ocr(lines)

    cleaned_invoice_text = "\n".join(lines)

    return (
        "=== CURRENCY DATABASE (REFERENCE) ===\n"
        f"{currency_db_str}\n\n"
        "=== INVOICE CONTENT ===\n"
        f"{cleaned_invoice_text}"
    )


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


def _resolve_models(model_id: str | None) -> tuple[ModelTarget, ModelTarget]:
    from ..runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    return primary_model, fallback_model


def _build_header_metadata(context: str) -> tuple[str, dict]:
    header_context = extract_header(context)
    header_meta = parse_header_metadata(header_context)
    for key, value in parse_full_doc_metadata(context).items():
        if key not in header_meta:
            header_meta[key] = value
    return header_context, header_meta


def _extract_with_timing(context: str, header_context: str, model: ModelTarget) -> dict:
    with timer() as t_llm:
        raw_output, annotated_doc, usage = extract_with_langextract_optimized(context, model, header_context)
    with timer() as t_validate:
        validation = validate_and_parse(raw_output)
    return {
        "raw_output": raw_output,
        "annotated_doc": annotated_doc,
        "usage": usage,
        "validation": validation,
        "llm_seconds": t_llm[0],
        "validate_seconds": t_validate[0],
    }


def _fill_derived_item_fields(items: list[dict]) -> list[dict]:
    for item in items:
        cost = item.get("cost")
        is_empty_cost = cost is None or str(cost).strip().lower() in ("", "null", "none", "0")
        if is_empty_cost:
            try:
                price = float(item.get("price") or 0)
                qty = float(item.get("quantity") or 1)
                item["cost"] = round(price / qty, 4) if qty else price
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        unit = item.get("unit")
        if unit is None or str(unit).strip().lower() in ("", "null", "none"):
            item["unit"] = "pcs"
    return items


def _normalize_items(items: list[dict], header_meta: dict, currency_db: list[dict]) -> list[dict]:
    normalized = post_fill_from_header(items, header_meta, currency_db)
    normalized = _fill_derived_item_fields(normalized)
    normalized = spread_single_country_origin(normalized)
    normalized = finalize_items(normalized, currency_db)
    normalized = filter_ocr_anomalies(normalized)
    return sort_items_by_position(deduplicate_items(normalized))


def _recover_with_structured_items(
    llm_items: list[dict],
    structured_items: list[dict],
    header_meta: dict,
    currency_db: list[dict],
) -> list[dict]:
    if not structured_items:
        return llm_items

    structured_final_items = _normalize_items(structured_items, header_meta, currency_db)
    if not structured_final_items:
        return llm_items

    if len(structured_final_items) < max(len(llm_items) + 5, 10):
        return llm_items

    positioned_llm_items = [item for item in llm_items if item.get("position") is not None]
    merged_items = deduplicate_items(positioned_llm_items + structured_final_items)
    if len(merged_items) >= len(structured_final_items):
        return sort_items_by_position(merged_items)
    return sort_items_by_position(structured_final_items)


def run_invoice_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """
    Full pipeline for document_code == '04021'.
    """
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    currency_db = load_currency_db()
    currency_db_str = build_currency_db_string(currency_db)

    with timer() as t:
        context = clean_text(ocr_draft, currency_db_str)
    metrics.t_clean_s = t[0]
    primary_model, fallback_model = _resolve_models(model_id)
    effective_model = primary_model.model_id

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {"error": "Empty OCR text", "metrics": metrics.to_dict(), "model_id": effective_model}

    header_context, header_meta = _build_header_metadata(context)
    structured_items = extract_structured_pipe_items(context)
    primary_result = _extract_with_timing(context, header_context, primary_model)
    raw_output = primary_result["raw_output"]
    annotated_doc = primary_result["annotated_doc"]
    validation = primary_result["validation"]
    metrics.t_primary_llm_s = primary_result["llm_seconds"]
    metrics.t_validate_s = primary_result["validate_seconds"]
    if primary_result["usage"]:
        metrics.token_usage["primary"] = primary_result["usage"]
    metrics.primary_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.fallback_used = True
        effective_model = fallback_model.model_id
        fallback_result = _extract_with_timing(context, header_context, fallback_model)
        raw_output = fallback_result["raw_output"]
        annotated_doc = fallback_result["annotated_doc"]
        validation = fallback_result["validation"]
        metrics.t_fallback_llm_s = fallback_result["llm_seconds"]
        metrics.t_validate_s += fallback_result["validate_seconds"]
        if fallback_result["usage"]:
            metrics.token_usage["fallback"] = fallback_result["usage"]
        metrics.fallback_valid = bool(validation["is_valid"])

    if not validation["is_valid"]:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": validation.get("error", "Extraction failed after fallback"),
            "metrics": metrics.to_dict(),
            "model_id": effective_model,
        }

    with timer() as t:
        final_items = _normalize_items(validation["data"]["items"], header_meta, currency_db)
        final_items = _recover_with_structured_items(final_items, structured_items, header_meta, currency_db)
    metrics.t_finalize_s = t[0]

    metrics.items_extracted = len(final_items)
    metrics.field_fill_rates = compute_field_fill_rates(final_items)
    total_usage = merge_token_usage(
        metrics.token_usage.get("primary", {}),
        metrics.token_usage.get("fallback", {}),
    )
    if total_usage:
        metrics.token_usage["total"] = total_usage
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"items": final_items, "count": len(final_items)},
        "metrics": metrics.to_dict(),
        "annotated_doc": annotated_doc,
        "model_id": effective_model,
        "raw_llm_output": raw_output,
    }


class InvoiceHandler(DocumentHandler):
    document_code = "04021"
    label = "Invoice"
    schema = DocumentSchema(
        result_type="table",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("country_sender", "Country Sender"),
        ),
        item_fields=(
            DocumentFieldSchema("position", "Position", kind="integer"),
            DocumentFieldSchema("description", "Description"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("quantity", "Quantity", kind="number"),
            DocumentFieldSchema("unit", "Unit"),
            DocumentFieldSchema("cost", "Cost", kind="number"),
            DocumentFieldSchema("price", "Price", kind="number"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("country_origin_code", "Country Origin Code", kind="integer"),
            DocumentFieldSchema("country_sender", "Country Sender"),
        ),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = run_invoice_extraction(ocr_draft, model_id=model or None)
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": {}, "items": [], "count": 0},
            }

        result = output.get("result", {})
        items = result.get("items", [])
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {
                "fields": {},
                "items": items,
                "count": len(items),
            },
        }


TD_EXTRACTION_PROMPT = """
# ROLE
You are an expert technical-document data extractor.

# TASK
You are given OCR text from a Technical Specification document. The text may have
mixed formats, irregular structure, and OCR artifacts.

Extract structured data for ALL products/items listed in the document.

For each product found, extract:
- `product_name` — product/item name
- `technical_description` — technical description as a single string
- `hs_code` — HS code, if not found set null
- `model` — model / article / SKU
- `country_origin` — manufacturer or country of origin
- `document_date` — document date, normalize to DD/MM/YYYY when possible; if not
  found use exactly `NO_DATE_FOUND`
- `document_number` — document number, if not found set null

# RULES
- Ignore headers, footers, signatures, stamps, and decorative boilerplate.
- Normalize dates when possible.
- If a field cannot be found for a specific item, set it to null.
- `technical_description` must always be a single plain string, never an object.
- If specifications are key-value, convert them to plain multiline text.
- Keep original source language.
"""

TD_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Technical Specification No. TD-55\n"
            "Date: 09/10/2025\n"
            "1. Product: Pressure Sensor PS-200\n"
            "Specifications: Range 0-10 bar; Material stainless steel; Output 4-20mA\n"
            "HS code: 9026202000\n"
            "Origin: Germany\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="technical_document_item",
                extraction_text="Pressure Sensor PS-200",
                attributes={
                    "product_name": "Pressure Sensor PS-200",
                    "technical_description": "Range: 0-10 bar\nMaterial: stainless steel\nOutput: 4-20mA",
                    "hs_code": "9026202000",
                    "model": "PS-200",
                    "country_origin": "Germany",
                    "document_date": "09/10/2025",
                    "document_number": "TD-55",
                },
            )
        ],
    ),
    lx.data.ExampleData(
        text=(
            "SPECIFICATION REF. TS-88/24\n"
            "Issued on 2024-11-18\n"
            "Item: Cable Gland M20\n"
            "Description: Polyamide cable gland for industrial cabinet assembly\n"
            "Country of origin: China\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="technical_document_item",
                extraction_text="Cable Gland M20",
                attributes={
                    "product_name": "Cable Gland M20",
                    "technical_description": "Polyamide cable gland for industrial cabinet assembly",
                    "hs_code": None,
                    "model": "M20",
                    "country_origin": "China",
                    "document_date": "18/11/2024",
                    "document_number": "TS-88/24",
                },
            )
        ],
    ),
]

TD_ITEM_FIELDS = (
    "product_name",
    "technical_description",
    "hs_code",
    "model",
    "country_origin",
    "document_date",
    "document_number",
)


def clean_technical_document_text(ocr_draft: str) -> str:
    """Normalize OCR text for technical document extraction."""
    text = html.unescape(ocr_draft or "")
    if not text.strip():
        return ""

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(p|div|span|table|tbody|thead|tr|td|th)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", " ")
    text = text.replace("\xa0", " ")

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t|")
        if not line:
            continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _td_to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = re.sub(r"[ \t]+", " ", str(value)).strip()
        return text or None
    return None


def _td_flatten_to_lines(value: object, lines: list[str], parent_key: str = "") -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for key, inner_value in value.items():
            key_text = _td_to_text(key) or parent_key
            if isinstance(inner_value, (dict, list)):
                _td_flatten_to_lines(inner_value, lines, key_text)
            else:
                value_text = _td_to_text(inner_value)
                if not value_text:
                    continue
                lines.append(f"{key_text}: {value_text}" if key_text else value_text)
        return
    if isinstance(value, list):
        for inner_value in value:
            if isinstance(inner_value, (dict, list)):
                _td_flatten_to_lines(inner_value, lines, parent_key)
            else:
                value_text = _td_to_text(inner_value)
                if not value_text:
                    continue
                lines.append(f"{parent_key}: {value_text}" if parent_key else value_text)
        return
    value_text = _td_to_text(value)
    if value_text:
        lines.append(f"{parent_key}: {value_text}" if parent_key else value_text)


def _td_description_to_text(value: object) -> str | None:
    scalar = _td_to_text(value)
    if scalar is not None:
        return scalar
    if isinstance(value, (dict, list)):
        lines: list[str] = []
        _td_flatten_to_lines(value, lines)
        text = "\n".join(line for line in lines if line.strip()).strip()
        return text or None
    return None


def _td_normalize_date(value: object) -> str:
    text = _td_to_text(value)
    if not text or text.upper() == "NO_DATE_FOUND":
        return datetime.now().strftime("%d/%m/%Y")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    compact = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if compact:
        day, month, year = compact.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"
    return text


def _resolve_td_model(model_id: str | None):
    from ..runtime import get_runtime_settings

    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    if primary_model.provider != "cerebras":
        return primary_model, False

    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    if fallback_model.provider == "cerebras":
        raise ValueError(
            "Technical document extraction requires a LangExtract-backed model "
            "(gemini, openai, or ollama)."
        )
    return fallback_model, True


def _normalize_td_items(extractions: list[dict[str, object]]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for extraction in extractions:
        attributes = extraction.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}

        item: dict[str, object] = {field: None for field in TD_ITEM_FIELDS}
        item.update(attributes)
        item["product_name"] = _td_to_text(item.get("product_name")) or _td_to_text(
            extraction.get("extraction_text")
        )
        item["technical_description"] = _td_description_to_text(item.get("technical_description"))
        item["hs_code"] = _td_to_text(item.get("hs_code"))
        item["model"] = _td_to_text(item.get("model"))
        item["country_origin"] = _td_to_text(item.get("country_origin"))
        item["document_date"] = _td_normalize_date(item.get("document_date"))
        item["document_number"] = _td_to_text(item.get("document_number"))

        if not item["product_name"] and not item["technical_description"]:
            continue
        items.append(item)
    return items


def _validate_td_items(items: list[dict[str, object]]) -> tuple[bool, str]:
    if not items:
        return False, "No technical document items extracted"
    for item in items:
        for key in TD_ITEM_FIELDS:
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                return False, f"'{key}' must be a string or null"
    return True, ""


def _build_td_fields(items: list[dict[str, object]]) -> dict[str, object]:
    fields = {"document_number": None, "document_date": None}
    for item in items:
        if not fields["document_number"] and item.get("document_number"):
            fields["document_number"] = item["document_number"]
        if not fields["document_date"] and item.get("document_date"):
            fields["document_date"] = item["document_date"]
    return fields


def run_technical_document_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '09022'."""
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    with timer() as t_clean:
        context = clean_technical_document_text(ocr_draft)
    metrics.t_clean_s = t_clean[0]

    target_model, implicit_fallback = _resolve_td_model(model_id)
    metrics.fallback_used = implicit_fallback

    if not context:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": "Empty OCR text",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    with timer() as t_llm:
        extractions, _annotated_doc, usage = extract_with_langextract_entities(
            context,
            target_model,
            prompt_description=TD_EXTRACTION_PROMPT,
            examples=TD_EXAMPLES,
        )
    metrics.t_primary_llm_s = t_llm[0]
    if usage:
        metrics.token_usage["primary"] = usage

    with timer() as t_validate:
        items = _normalize_td_items(extractions)
        is_valid, error = _validate_td_items(items)
    metrics.t_validate_s = t_validate[0]
    metrics.primary_valid = is_valid

    if not is_valid:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": error or "Technical document extraction failed",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    metrics.items_extracted = len(items)
    metrics.field_fill_rates = compute_field_fill_rates(items)
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"fields": _build_td_fields(items), "items": items, "count": len(items)},
        "metrics": metrics.to_dict(),
        "model_id": target_model.model_id,
    }


class TechnicalDocumentHandler(DocumentHandler):
    document_code = "09022"
    label = "Technical Document"
    schema = DocumentSchema(
        result_type="table",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
        ),
        item_fields=(
            DocumentFieldSchema("product_name", "Product Name"),
            DocumentFieldSchema("technical_description", "Technical Description"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("model", "Model"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("document_number", "Document Number"),
        ),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        output = run_technical_document_extraction(ocr_draft, model_id=model or None)
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": {}, "items": [], "count": 0},
            }

        result = output.get("result", {})
        items = result.get("items", [])
        fields = result.get("fields", {})
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {
                "fields": fields,
                "items": items,
                "count": len(items),
            },
        }
