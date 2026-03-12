"""Text normalization and metadata extraction helpers."""

import html
import re
from collections import Counter

from .prompts import (
    _FOOTER_PATTERNS,
    _HEADER_PATTERNS,
    _ISO4217_NUMERIC_TO_ALPHA3,
    _ITEM_ROW_START_RE,
    _PRICE_RE,
    _TABLE_HEADER_RE,
)

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
