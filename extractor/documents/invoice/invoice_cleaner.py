from __future__ import annotations

import html
import re
from collections import Counter

from ...normalizers.currency import resolve_country_code
from .invoice_cleaner_compact import (
    compact_table_ocr as _compact_table_ocr_impl,
    looks_like_blob_noise as _looks_like_blob_noise_impl,
    normalize_item_schema as _normalize_item_schema_impl,
)
from .invoice_cleaner_pipe import normalize_pipe_table as _normalize_pipe_table_impl
from .invoice_cleaner_pipe import strip_markup_noise as _strip_markup_noise_impl
from .invoice_cleaner_rehydrate import rehydrate_flattened_ocr_markdown as _rehydrate_flattened_ocr_markdown_impl


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

_INLINE_BLOB_NUM_RE = r"(?:\d{1,5}(?:[.,'′]\d{1,3})?|\d{1,5}\s\d{2,3})"
_INLINE_BLOB_ROW_RE = re.compile(
    rf"(?P<pos>\d{{1,3}}[.,]\d{{1,3}}|\d{{3,6}})\s+"
    rf"(?P<desc>[A-Za-zА-Яа-яЁё0-9 +\-/().]{{3,90}}?)\s+"
    rf"(?P<decl>\d{{10,14}})\s+"
    rf"(?P<country>[A-Za-zА-Яа-яЁё.]+(?:\s+[A-Za-zА-Яа-яЁё.]+){{0,2}})\s+"
    rf"(?P<hs>\d{{8,10}})\s+"
    rf"(?P<qty>{_INLINE_BLOB_NUM_RE})\s+"
    rf"(?P<n1>{_INLINE_BLOB_NUM_RE})\s+"
    rf"(?P<n2>{_INLINE_BLOB_NUM_RE})\s+"
    rf"(?P<cost>{_INLINE_BLOB_NUM_RE})"
    rf"(?:\s+(?P<price>{_INLINE_BLOB_NUM_RE}))?"
)

_FOLLOWUP_NOISE_HINTS = (
    "order date",
    "please beware",
    "carry-over",
    "carry-over:",
    "net we",
    "total amount",
    "payment terms",
    "value (eu)",
    "iban",
    "bic",
)

_BR_TAG_RE = re.compile(r"(?i)<br\s*/?>")
_EMBEDDED_CHAIN_HEAD_RE = re.compile(
    r"\|\s*(?P<pos>\d{1,3})\s*\|\s*(?P<part>\d{4,14})(?P<hint>[^\|]*)\s*$"
)
_ORDER_CHAIN_PREFIX_RE = re.compile(r"(?i)^\s*(?:Order date:[^|]*\||Please beware:\s*\|?)\s*")


def _rehydrate_flattened_ocr_markdown(text: str) -> str:
    return _rehydrate_flattened_ocr_markdown_impl(text)


def _normalize_pipe_table(text: str) -> str:
    return _normalize_pipe_table_impl(text)


def _strip_markup_noise(text: str) -> str:
    return _strip_markup_noise_impl(text)


def _strip_inline_markup(fragment: str) -> str:
    text = html.unescape(fragment or "")
    text = re.sub(r"</?[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_stacked_marker_pipe_row(cells: list[str]) -> bool:
    if len(cells) < 5:
        return False

    pos_parts = [_strip_inline_markup(part) for part in _BR_TAG_RE.split(cells[0])]
    pos_parts = [part for part in pos_parts if part]
    article_parts = [_strip_inline_markup(part) for part in _BR_TAG_RE.split(cells[1])]
    article_parts = [part for part in article_parts if part]

    if len(pos_parts) < 2 or len(pos_parts) != len(article_parts):
        return False
    if not all(re.fullmatch(r"(?:\d{1,3}|[+\-])", part) for part in pos_parts):
        return False
    if not all(_looks_like_article_cell(part) for part in article_parts):
        return False
    return True


def _expand_stacked_marker_pipe_rows(text: str) -> str:
    expanded_lines: list[str] = []

    for line in text.split("\n"):
        if "|" not in line or "<br" not in line.lower():
            expanded_lines.append(line)
            continue

        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if not _looks_like_stacked_marker_pipe_row(cells):
            expanded_lines.append(line)
            continue

        split_cells: list[list[str]] = []
        row_count = 0
        for cell in cells:
            parts = [_strip_inline_markup(part) for part in _BR_TAG_RE.split(cell)]
            parts = [part for part in parts if part]
            split_cells.append(parts)
            row_count = max(row_count, len(parts))

        if row_count < 2:
            expanded_lines.append(line)
            continue

        for row_idx in range(row_count):
            row_cells: list[str] = []
            for parts in split_cells:
                if len(parts) == row_count:
                    row_cells.append(parts[row_idx])
                elif len(parts) == 1:
                    row_cells.append(parts[0])
                else:
                    row_cells.append(" ".join(parts))
            expanded_lines.append("| " + " | ".join(row_cells) + " |")

    return "\n".join(expanded_lines)


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
    has_price = bool(re.search(r"\b\d+[.,]\d{2}\b", line))
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
    return _normalize_article_cell(cell) is not None


def _normalize_article_cell(value: str) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if re.fullmatch(r"\d{4,14}", text):
        return text
    repeated = re.fullmatch(r"(\d{4,14})(?:\s+\1)+", text)
    if repeated:
        return repeated.group(1)
    return None


def _looks_like_marker_cell(cell: str) -> bool:
    cell = cell.strip()
    if not cell:
        return True
    if re.fullmatch(r"[+\-*•]+", cell):
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
    if not re.search(r"\b\d+[.,]\d{2}\b", line) and meaningful_cells < 5 and short_cells >= max(4, len(cells) // 2):
        return True
    return False


def _looks_like_blob_noise(line: str) -> bool:
    return _looks_like_blob_noise_impl(
        line,
        looks_like_boilerplate_line=_looks_like_boilerplate_line,
    )


def _is_numericish_cell(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"\d", value)) and bool(re.fullmatch(r"[\d\s,.'′/\-]+", value))


def _is_hs_like_cell(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 6 <= len(digits) <= 10


def _is_terminal_hs_cell(value: str) -> bool:
    text = str(value or "").strip()
    if not _is_hs_like_cell(text):
        return False
    return not any(marker in text for marker in (",", ".", "'", "′"))


def _is_declaration_like_cell(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 10 <= len(digits) <= 14


def _is_country_like_cell(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", value)) and not _is_numericish_cell(value)


def _is_article_like_cell(value: str) -> bool:
    return _normalize_article_cell(value) is not None


def _is_pure_code_like_cell(value: str) -> bool:
    text = str(value or "").strip()
    if not text or " " in text or any(marker in text for marker in (",", ".", "'", "′")):
        return False
    return bool(re.fullmatch(r"\d{6,14}", text))


def _is_marker_like_cell(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return True
    if re.fullmatch(r"[+\-*•]+", value):
        return True
    if _is_article_like_cell(value):
        return False
    return bool(re.fullmatch(r"[\d\s,./+\-]{1,8}", value))


def _looks_like_positionless_marker_companion_line(line: str) -> bool:
    if not _is_pipe_table_line(line) or _is_table_item_line(line):
        return False

    cells = _table_cells(line)
    if len(cells) < 6:
        return False
    if not _is_marker_like_cell(cells[0]):
        return False
    if not _is_terminal_hs_cell(cells[-1]):
        return False

    text_cells = sum(bool(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell)) for cell in cells[1:-1])
    numeric_cells = sum(_is_numericish_cell(cell) for cell in cells[1:-1])
    has_country = any(_is_country_like_cell(cell) for cell in cells[1:-1])
    return text_cells >= 1 and numeric_cells >= 2 and has_country


def _parse_loose_number(value) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    text = text.replace("′", "'")
    text = re.sub(r"\s+", " ", text)

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


def normalize_hs_code(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if 6 <= len(digits) <= 10:
        return digits
    return None


def _normalize_inline_blob_position(value: str) -> int | None:
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 3 or len(digits) > 6:
        return None
    if raw.startswith("0") and len(digits) >= 5:
        return None
    try:
        position = int(digits)
    except ValueError:
        return None
    return position if position > 0 else None


def _format_numeric_cell(value: float) -> str:
    rounded = round(float(value), 4)
    if abs(rounded - round(rounded)) <= 0.0001:
        return f"{int(round(rounded))},00"
    return f"{rounded:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _normalize_inline_blob_item(match: re.Match[str]) -> str | None:
    position = _normalize_inline_blob_position(match.group("pos"))
    if position is None:
        return None

    description = re.sub(r"\s+", " ", match.group("desc").replace("|", " ")).strip()
    if len(description) < 3 or not re.search(r"[A-Za-zА-Яа-яЁё]{2,}", description):
        return None

    country = re.sub(r"\s+", " ", match.group("country")).strip()
    if not _is_country_like_cell(country):
        return None

    hs_code = normalize_hs_code(match.group("hs"))
    if not hs_code:
        return None

    quantity = _parse_loose_number(match.group("qty"))
    cost = _parse_loose_number(match.group("cost"))
    price = _parse_loose_number(match.group("price"))
    if quantity is None or quantity <= 0:
        return None
    if cost is None or cost <= 0:
        return None

    expected_total = quantity * cost
    if price is None or price <= 0:
        price = expected_total
    else:
        ratio = price / max(expected_total, 1.0)
        if price < cost or ratio < 0.55 or ratio > 5:
            if expected_total > 0:
                price = expected_total

    if price <= 0:
        return None

    if expected_total > 0:
        ratio = price / expected_total
        if ratio < 0.55 or ratio > 5:
            cost = price / quantity
    if cost <= 0:
        return None

    return (
        "| "
        + " | ".join(
            [
                str(position),
                description,
                match.group("decl"),
                country,
                hs_code,
                _format_numeric_cell(quantity),
                match.group("n1"),
                match.group("n2"),
                _format_numeric_cell(cost),
                _format_numeric_cell(price),
            ]
        )
        + " |"
    )


def _extract_inline_blob_pipe_rows(line: str) -> list[str]:
    if len(line) < 250 or not _is_table_item_line(line):
        return []

    flat = re.sub(r"\s+", " ", line.replace("|", " ")).strip()
    if not flat:
        return []

    embedded_rows: list[str] = []
    for index, match in enumerate(_INLINE_BLOB_ROW_RE.finditer(flat)):
        if index == 0:
            continue
        normalized = _normalize_inline_blob_item(match)
        if normalized is None:
            continue
        embedded_rows.append(normalized)
    return embedded_rows


def _looks_like_valid_hs_last_prefix(cells: list[str]) -> bool:
    if len(cells) < 8 or not _is_terminal_hs_cell(cells[-1]):
        return False
    if not any(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell) for cell in cells[1:-1]):
        return False

    for idx in range(max(1, len(cells) - 5), len(cells) - 1):
        if not _is_country_like_cell(cells[idx]):
            continue
        tail = cells[idx + 1 : -1]
        if len(tail) < 2:
            continue
        numericish = sum(_is_numericish_cell(cell) for cell in tail)
        if numericish >= 2:
            return True
    return False


def _looks_like_followup_row_suffix(cells: list[str]) -> bool:
    if not cells:
        return False

    joined = " ".join(str(cell or "").strip() for cell in cells if str(cell or "").strip())
    if not joined:
        return False

    if any(_looks_like_article_cell(cell) for cell in cells[:2]):
        return True
    if len(cells) >= 2 and _is_marker_like_cell(cells[0]) and _looks_like_article_cell(cells[1]):
        return True
    if re.search(r"\b\d{1,3}\s+\d{4,14}\b", joined):
        return True
    if len(cells) >= 3 and _is_country_like_cell(cells[-2]) and _is_hs_like_cell(cells[-1]):
        return True

    text_cells = sum(bool(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell)) for cell in cells)
    numericish = sum(_is_numericish_cell(cell) or _is_hs_like_cell(cell) for cell in cells)
    trivial_noise = sum(
        bool(re.fullmatch(r"[•.\-_/]+", str(cell or "").strip()))
        or str(cell or "").strip() in {"0", "00", "000"}
        for cell in cells
    )
    if trivial_noise == len(cells):
        return True
    return text_cells >= 1 and numericish <= 1


def _is_followup_noise_cell(value: str) -> bool:
    lower = str(value or "").strip().lower()
    if not lower:
        return False
    return any(hint in lower for hint in _FOLLOWUP_NOISE_HINTS)


def _looks_like_valid_compact_prefix(cells: list[str]) -> bool:
    work = [str(cell or "").strip() for cell in cells if str(cell or "").strip()]
    if len(work) < 6:
        return False

    if len(work) >= 2 and _looks_like_marker_cell(work[0]) and _looks_like_article_cell(work[1]):
        work[1] = _normalize_article_cell(work[1]) or work[1]
        work = work[1:]
    if len(work) < 5 or not _looks_like_article_cell(work[0]):
        return False
    work[0] = _normalize_article_cell(work[0]) or work[0]

    if not any(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell) for cell in work[1:4]):
        return False

    if _looks_like_valid_hs_last_prefix(work):
        return True

    numeric_tail = sum(_is_numericish_cell(cell) for cell in work[-3:])
    return numeric_tail >= 2


def _trim_item_line(line: str) -> str:
    cells = _table_cells(line)

    def _format_cells(raw_cells: list[str]) -> str:
        formatted = list(raw_cells)
        for idx in range(min(2, len(formatted))):
            normalized_article = _normalize_article_cell(formatted[idx])
            if normalized_article is not None:
                formatted[idx] = normalized_article
        return "| " + " | ".join(formatted) + " |"

    def _looks_like_separator_suffix(raw_cells: list[str]) -> bool:
        if not raw_cells:
            return False
        return all(re.fullmatch(r"[- ]{3,}", str(cell or "").strip()) is not None for cell in raw_cells)

    def _looks_like_hs_row_prefix(raw_cells: list[str]) -> bool:
        if len(raw_cells) < 8:
            return False
        if normalize_hs_code(raw_cells[-1]) is None:
            return False
        if sum(_parse_loose_number(cell) is not None for cell in raw_cells[-4:-1]) < 3:
            return False
        if not any(_is_country_like_cell(cell) for cell in raw_cells[2:-3]):
            return False
        return any(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell) for cell in raw_cells[1:-4])

    for idx, cell in enumerate(cells):
        if not _is_followup_noise_cell(cell):
            continue
        prefix = cells[:idx]
        if _looks_like_valid_compact_prefix(prefix):
            return _format_cells(prefix)

    if len(cells) >= 10:
        for prefix_len in range(8, len(cells)):
            prefix = cells[:prefix_len]
            suffix = cells[prefix_len:]
            if _looks_like_valid_hs_last_prefix(prefix) and _looks_like_followup_row_suffix(suffix):
                return _format_cells(prefix)
            if _looks_like_hs_row_prefix(prefix) and _looks_like_separator_suffix(suffix):
                return _format_cells(prefix)

    if len(cells) >= 10 and not _is_table_item_line(line):
        for start_idx in range(1, len(cells) - 5):
            suffix = cells[start_idx:]
            article_led_suffix = _looks_like_article_cell(suffix[0]) and not (
                len(suffix) >= 2 and re.fullmatch(r"\d{1,3}|[+\-]", str(suffix[1]).strip())
            )
            if not (
                article_led_suffix
                or (
                    len(suffix) >= 2
                    and re.fullmatch(r"\d{1,3}|[+\-]", str(suffix[0]).strip())
                    and _looks_like_article_cell(suffix[1])
                )
            ):
                continue
            if not _looks_like_valid_compact_prefix(suffix):
                continue
            prefix = cells[:start_idx]
            if _looks_like_valid_compact_prefix(prefix) or _looks_like_valid_hs_last_prefix(prefix):
                continue
            return _format_cells(suffix)

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

    return _format_cells(cells[:max_cells])


def _normalize_item_schema(lines: list[str]) -> list[str]:
    return _normalize_item_schema_impl(
        lines,
        is_table_item_line=_is_table_item_line,
        table_cells=_table_cells,
        looks_like_article_cell=_looks_like_article_cell,
        looks_like_marker_cell=_looks_like_marker_cell,
        trim_item_line=_trim_item_line,
    )


def _compact_table_ocr(lines: list[str]) -> list[str]:
    return _compact_table_ocr_impl(
        lines,
        is_pipe_table_line=_is_pipe_table_line,
        is_table_item_line=_is_table_item_line,
        looks_like_positionless_marker_companion_line=_looks_like_positionless_marker_companion_line,
        looks_like_pipe_noise=_looks_like_pipe_noise,
        extract_inline_blob_pipe_rows=_extract_inline_blob_pipe_rows,
        trim_item_line=_trim_item_line,
        looks_like_blob_noise=_looks_like_blob_noise,
        looks_like_boilerplate_line=_looks_like_boilerplate_line,
        boilerplate_key=_boilerplate_key,
        normalize_item_schema=_normalize_item_schema,
    )


def _clean_embedded_chain_description(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"(?i)\byour used part no\b.*$", "", text)
    text = re.sub(r"(?i)\bplease beware\b[: ]*", "", text)
    text = re.sub(r"(?i)\b-?\s*avia\b", "", text)
    text = re.sub(r"(?i)\b\d{1,2}[.,]\d{1,2}(?:[.,]\d{2,4})?\b", "", text)
    text = re.sub(r"(?i)\b\d{4}\b", "", text)
    text = re.sub(r"\b\d{1,3}\b", " ", text)
    text = re.sub(r"[•_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -,:;|.")


def _extract_embedded_chain_head(line: str) -> tuple[int, str, str] | None:
    if "|" not in line:
        return None

    match = _EMBEDDED_CHAIN_HEAD_RE.search(line)
    if match is None:
        return None

    lower = line.lower()
    if lower.startswith("order date:") or lower.startswith("please beware:"):
        return None

    headless_payload = lower.count("|") <= 4 and "pos" not in lower and "part no" not in lower
    if headless_payload:
        letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", line)
        if len(letters) > 20:
            return None

    return (
        int(match.group("pos")),
        match.group("part"),
        _clean_embedded_chain_description(match.group("hint")),
    )


def _extract_embedded_chain_tail(line: str) -> tuple[str, tuple[int, str, str] | None]:
    match = _EMBEDDED_CHAIN_HEAD_RE.search(line)
    if match is None:
        return line, None

    body = line[: match.start()].rstrip(" |")
    tail = (
        int(match.group("pos")),
        match.group("part"),
        _clean_embedded_chain_description(match.group("hint")),
    )
    return body, tail


def _is_embedded_order_chain_payload(line: str) -> bool:
    lower = str(line or "").strip().lower()
    return lower.startswith("order date:") or lower.startswith("please beware:")


def _extract_embedded_chain_quantity(value: str) -> float | None:
    parsed = _parse_loose_number(value)
    if parsed is not None and 0 < parsed <= 1000:
        rounded = round(parsed)
        if abs(parsed - rounded) <= 0.12:
            return float(rounded)

    for group in re.findall(r"\d+", str(value or "")):
        try:
            candidate = int(group)
        except ValueError:
            continue
        if 0 < candidate <= 1000:
            return float(candidate)
    return None


def _extract_embedded_chain_country(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    compact = re.sub(r"[^A-Za-z]", "", text).upper()
    for size in (2, 3):
        if len(compact) >= size:
            code = compact[:size]
            if resolve_country_code(code) is not None:
                return code

    if _is_country_like_cell(text):
        return text
    return None


def _build_embedded_chain_row(
    head: tuple[int, str, str],
    payload_line: str,
) -> str | None:
    payload = _ORDER_CHAIN_PREFIX_RE.sub("", payload_line, count=1)
    raw_cells = [cell.strip() for cell in payload.split("|") if cell.strip()]
    if not raw_cells:
        return None

    numeric_cells: list[tuple[int, float]] = []
    for idx, cell in enumerate(raw_cells):
        parsed = _parse_loose_number(cell)
        if parsed is None or parsed <= 0:
            continue
        numeric_cells.append((idx, parsed))
    if len(numeric_cells) < 2:
        return None

    price_idx, price = numeric_cells[-1]
    cost_idx, cost = numeric_cells[-2]
    if price <= 0 or cost <= 0 or price < cost:
        return None

    qty = None
    qty_idx = None
    for idx in range(cost_idx - 1, -1, -1):
        qty = _extract_embedded_chain_quantity(raw_cells[idx])
        if qty is not None:
            qty_idx = idx
            break
    if qty is None:
        inferred_qty = round(price / cost) if cost > 0 else 0
        if 0 < inferred_qty <= 1000 and abs(price - inferred_qty * cost) <= max(1.0, 0.05 * price):
            qty = float(inferred_qty)
    if qty is None or qty <= 0:
        return None

    country = None
    country_idx = None
    search_stop = qty_idx if qty_idx is not None else cost_idx
    for idx in range(search_stop - 1, -1, -1):
        country = _extract_embedded_chain_country(raw_cells[idx])
        if country is not None:
            country_idx = idx
            break

    description_parts: list[str] = []
    if head[2]:
        description_parts.append(head[2])
    description_stop = country_idx if country_idx is not None else (qty_idx if qty_idx is not None else cost_idx)
    for idx in range(description_stop):
        cleaned = _clean_embedded_chain_description(raw_cells[idx])
        if not cleaned:
            continue
        if _parse_loose_number(cleaned) is not None:
            continue
        if _extract_embedded_chain_country(cleaned) is not None and len(re.sub(r"[^A-Za-zА-Яа-яЁё]", "", cleaned)) <= 4:
            continue
        description_parts.append(cleaned)

    description_parts = [part for part in description_parts if part]
    if not description_parts:
        return None

    description = re.sub(r"\s+", " ", " ".join(description_parts)).strip()
    row_cells = [str(head[0]), head[1], description]
    if country is not None:
        row_cells.append(country)
    row_cells.extend([_format_numeric_cell(qty), _format_numeric_cell(cost), _format_numeric_cell(price)])
    return "| " + " | ".join(row_cells) + " |"


def _rehydrate_embedded_order_date_chains(lines: list[str]) -> list[str]:
    if not lines:
        return lines

    rebuilt: list[str] = []
    idx = 0
    while idx < len(lines):
        head = _extract_embedded_chain_head(lines[idx])
        if head is None:
            rebuilt.append(lines[idx])
            idx += 1
            continue

        probe = idx + 1
        if probe >= len(lines) or not _is_embedded_order_chain_payload(lines[probe]):
            rebuilt.append(lines[idx])
            idx += 1
            continue

        pending = head
        idx += 1
        while idx < len(lines):
            line = lines[idx]
            if not _is_embedded_order_chain_payload(line):
                break

            body, next_head = _extract_embedded_chain_tail(line)
            rebuilt_row = _build_embedded_chain_row(pending, body)
            if rebuilt_row is not None:
                rebuilt.append(rebuilt_row)

            if next_head is not None:
                pending = next_head
                idx += 1
                continue

            idx += 1
            while idx < len(lines) and _is_embedded_order_chain_payload(lines[idx]):
                body, next_head = _extract_embedded_chain_tail(lines[idx])
                rebuilt_row = _build_embedded_chain_row(pending, body)
                if rebuilt_row is not None:
                    rebuilt.append(rebuilt_row)
                idx += 1
                if next_head is not None:
                    pending = next_head
                    break
            else:
                pending = None
            if pending is None:
                break

        continue

    return rebuilt


def clean_text(raw_text: str, currency_db_str: str) -> str:
    if not raw_text:
        return ""

    text = _rehydrate_flattened_ocr_markdown(raw_text)
    text = _normalize_pipe_table(text)
    text = _expand_stacked_marker_pipe_rows(text)
    text = _strip_markup_noise(text)
    text = _normalize_pipe_table(text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = []
    for line in text.split("\n"):
        clean_line = re.sub(r"[ \t]+", " ", line).strip()
        if clean_line and clean_line != "|":
            lines.append(clean_line)

    if sum(_is_pipe_table_line(line) for line in lines) >= 8:
        lines = _compact_table_ocr(lines)
    lines = _rehydrate_embedded_order_date_chains(lines)

    cleaned_invoice_text = "\n".join(lines)

    return (
        "=== CURRENCY DATABASE (REFERENCE) ===\n"
        f"{currency_db_str}\n\n"
        "=== INVOICE CONTENT ===\n"
        f"{cleaned_invoice_text}"
    )
