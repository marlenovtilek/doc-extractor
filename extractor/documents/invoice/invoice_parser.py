from __future__ import annotations

import re

from .invoice_cleaner import (
    _is_article_like_cell,
    _is_marker_like_cell,
    _is_table_item_line,
    _is_terminal_hs_cell,
    _parse_loose_number,
    _table_cells,
    _trim_item_line,
)
from .invoice_parser_extractors import (
    _extract_compact_no_hs_item,
    _extract_hs_last_item,
    _extract_hs_last_single_value_item,
    _extract_loose_hs_tail_item,
    _extract_partial_hs_companion_item,
    _extract_positionless_marker_hs_last_item,
    _extract_shifted_tail_item,
    _extract_sparse_hs_item_without_country,
    _parse_item_from_cells,
)
from .invoice_parser_support import (
    _build_structured_line_signature,
    _extract_part_no_from_cells,
    _extract_position_from_cells,
    _has_explicit_pos_part_no_layout,
    _normalized_article_digits,
    _positionless_companion_matches_item,
)

_LEADING_NOISE_RE = re.compile(
    r"(?:order\s+date|please\s+beware|carry-?over|payment\s+terms|net\s+we|total\s+amount)",
    re.IGNORECASE,
)
_PAGE_COUNTER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
_IMAGE_MARKDOWN_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_INVOICE_PAGE_HEADER_RE = re.compile(r"^\s*invoice\b.*\d+\s*/\s*\d+\s*$", re.IGNORECASE)
_AVIA_SERVICE_LINE_RE = re.compile(
    r"^\s*(?:[a-z0-9]{0,4}\s*[-–]\s*)?avia\s*$|^\s*[-–]\s*avia\s*$",
    re.IGNORECASE,
)
_SHORT_OCR_FRAGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z ]{2,40}$")
_TYPE_PREFIX_RU_MAP = {
    "belt": "Ремень",
    "bracket": "Кронштейн",
    "building kit": "Комплект",
    "cap": "Крышка",
    "clamp": "Хомут",
    "clip": "Фиксатор",
    "console": "Кронштейн",
    "cover": "Крышка",
    "gasket": "Прокладка",
    "guide pin": "Штифт",
    "handle": "Ручка",
    "hose": "Шланг",
    "nut": "Гайка",
    "o-ring": "Кольцо уплотнительное",
    "plug": "Заглушка",
    "repair kit": "Ремкомплект",
    "retainer": "Держатель",
    "ring": "Кольцо",
    "screw": "Винт",
    "sealing ring": "Кольцо уплотнительное",
    "sensor": "Датчик",
    "valve": "Клапан",
    "washer": "Шайба",
}


def _looks_like_split_item_head(cells: list[str]) -> bool:
    if len(cells) < 4 or len(cells) > 6:
        return False
    has_article = _is_article_like_cell(cells[0]) or (
        len(cells) >= 2 and _is_marker_like_cell(cells[0]) and _is_article_like_cell(cells[1])
    )
    if not has_article:
        return False
    hs_scan_start = (
        2
        if len(cells) >= 2 and _is_marker_like_cell(cells[0]) and _is_article_like_cell(cells[1])
        else 1
    )
    if any(_is_terminal_hs_cell(cell) for cell in cells[hs_scan_start:]):
        return False
    return any(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", cell) for cell in cells[1:])


def _looks_like_split_numeric_tail(cells: list[str]) -> bool:
    if len(cells) < 3 or len(cells) > 5:
        return False
    if not _is_terminal_hs_cell(cells[-1]):
        return False
    numeric_values = [
        _parse_loose_number(cell)
        for cell in cells[:-1]
        if _parse_loose_number(cell) is not None and _parse_loose_number(cell) > 0
    ]
    return len(numeric_values) >= 2 and not any(_is_article_like_cell(cell) for cell in cells[:2])


def _merge_split_item_lines(head_line: str, tail_line: str) -> str:
    head_cells = _table_cells(head_line)
    tail_cells = _table_cells(tail_line)
    return "| " + " | ".join([*head_cells, *tail_cells]) + " |"


def _merge_repeated_item_continuation_lines(head_line: str, tail_line: str) -> str:
    head_cells = _table_cells(head_line)
    tail_cells = _table_cells(tail_line)
    normalized_head = _normalized_cells_for_merge(head_cells)
    normalized_tail = _normalized_cells_for_merge(tail_cells)

    merged_head = list(head_cells[:2])
    type_prefix = None
    for candidate in normalized_head[1:]:
        text = str(candidate or "").strip()
        if not text or _parse_loose_number(text) is not None:
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z ./'-]{1,20}", text):
            type_prefix = text
            break

    preferred_description = None
    for candidate in normalized_head[1:]:
        text = str(candidate or "").strip()
        if re.search(r"[А-Яа-яЁё]{2,}", text):
            preferred_description = text
            break
    if preferred_description is None:
        for candidate in normalized_head[1:]:
            text = str(candidate or "").strip()
            if re.search(r"[A-Za-zА-Яа-яЁё]{2,}", text) and _parse_loose_number(text) is None:
                preferred_description = text
                break
    if (
        preferred_description is not None
        and type_prefix is not None
        and preferred_description != type_prefix
        and re.fullmatch(r"[а-яё0-9 .()\"'/-]{4,40}", preferred_description.lower()) is not None
        and preferred_description == preferred_description.lower()
    ):
        preferred_description = (
            f"{_TYPE_PREFIX_RU_MAP.get(type_prefix.strip().lower(), type_prefix)} {preferred_description}"
        )
    if preferred_description is not None:
        merged_head.append(preferred_description)

    tail_payload = normalized_tail[2:]
    payload_country = None
    payload_numeric: list[str] = []
    for cell in tail_payload:
        text = str(cell or "").strip()
        if not text:
            continue
        if payload_country is None and _is_terminal_hs_cell(text):
            continue
        if payload_country is None and re.fullmatch(r"[A-Za-z]{2,3}", text):
            payload_country = text
            continue
        if _parse_loose_number(text) is not None:
            payload_numeric.append(text)

    if payload_country is not None:
        merged_head.append(payload_country)

    return "| " + " | ".join([*merged_head, *payload_numeric]) + " |"


def _looks_like_merge_gap_noise(line: str) -> bool:
    raw = str(line or "").strip()
    lower = raw.lower()
    if not lower:
        return True
    if _LEADING_NOISE_RE.search(lower):
        return True
    if _PAGE_COUNTER_RE.fullmatch(raw):
        return True
    if _IMAGE_MARKDOWN_RE.fullmatch(raw):
        return True
    if _INVOICE_PAGE_HEADER_RE.fullmatch(raw):
        return True
    if _AVIA_SERVICE_LINE_RE.fullmatch(raw):
        return True
    if "|" in raw and not _is_table_item_line(raw):
        cells = [str(cell or "").strip() for cell in _table_cells(raw)]
        tokens = [cell for cell in cells if cell]
        joined = " ".join(tokens)
        if 1 <= len(tokens) <= 3 and joined:
            joined_lower = joined.lower()
            if _LEADING_NOISE_RE.search(joined_lower):
                return True
            if _AVIA_SERVICE_LINE_RE.fullmatch(joined):
                return True
            if _SHORT_OCR_FRAGMENT_RE.fullmatch(joined):
                words = re.findall(r"[A-Za-z]+", joined)
                if (
                    1 <= len(words) <= 3
                    and not any(_is_article_like_cell(token) for token in tokens)
                    and not any(_is_terminal_hs_cell(token) for token in tokens)
                    and not any(_parse_loose_number(token) is not None for token in tokens)
                ):
                    return True
        if 1 <= len(tokens) <= 4 and len(joined) <= 64:
            numeric_count = sum(_parse_loose_number(token) is not None for token in tokens)
            alpha_words = re.findall(r"[A-Za-z]+", joined)
            if (
                numeric_count <= 1
                and 1 <= len(alpha_words) <= 4
                and not any(_is_article_like_cell(token) for token in tokens)
                and not any(_is_terminal_hs_cell(token) for token in tokens)
            ):
                return True
    if "|" not in raw and _SHORT_OCR_FRAGMENT_RE.fullmatch(raw):
        words = re.findall(r"[A-Za-z]+", raw)
        if 1 <= len(words) <= 3:
            return True
    return "order date" in lower or "please beware" in lower


def _normalized_cells_for_merge(cells: list[str]) -> list[str]:
    if (
        len(cells) >= 2
        and _is_marker_like_cell(cells[0])
        and _is_article_like_cell(cells[1])
    ):
        normalized_article = _normalized_article_digits(cells[1]) or cells[1]
        return [normalized_article, *cells[2:]]
    return list(cells)


def _looks_like_repeated_item_numeric_continuation(
    head_cells: list[str],
    tail_cells: list[str],
) -> bool:
    if len(head_cells) < 4 or len(tail_cells) < 6:
        return False

    normalized_head = _normalized_cells_for_merge(head_cells)
    normalized_tail = _normalized_cells_for_merge(tail_cells)
    if len(normalized_head) < 3 or len(normalized_tail) < 5:
        return False
    if not _is_article_like_cell(normalized_head[0]) or not _is_article_like_cell(normalized_tail[0]):
        return False
    if normalized_head[0] != normalized_tail[0]:
        return False

    shared_hint = re.sub(r"\s+", " ", str(normalized_head[1] or "").strip().lower())
    if shared_hint and shared_hint != re.sub(r"\s+", " ", str(normalized_tail[1] or "").strip().lower()):
        return False

    head_numeric_values = [_parse_loose_number(cell) for cell in normalized_head[1:]]
    head_numeric_values = [value for value in head_numeric_values if value is not None]
    if len(head_numeric_values) > 1:
        return False
    if any(_is_terminal_hs_cell(cell) for cell in normalized_head[2:]):
        return False
    if any(_is_terminal_hs_cell(cell) for cell in normalized_tail[2:]):
        return False

    numeric_tail = [cell for cell in normalized_tail[2:] if _parse_loose_number(cell) is not None]
    if len(numeric_tail) < 2:
        return False

    descriptive_cells = [
        cell
        for cell in normalized_head[1:]
        if re.search(r"[A-Za-zА-Яа-яЁё]{2,}", str(cell or ""))
    ]
    return len(descriptive_cells) >= 2


def _repeated_item_merge_key(cells: list[str]) -> tuple[str, str] | None:
    normalized = _normalized_cells_for_merge(cells)
    if len(normalized) < 2 or not _is_article_like_cell(normalized[0]):
        return None
    hint = re.sub(r"\s+", " ", str(normalized[1] or "").strip().lower())
    if not hint:
        return None
    return (normalized[0], hint)


def _looks_like_pending_repeated_item_head(cells: list[str]) -> bool:
    normalized = _normalized_cells_for_merge(cells)
    if len(normalized) < 3 or not _is_article_like_cell(normalized[0]):
        return False
    numeric_values = [_parse_loose_number(cell) for cell in normalized[1:]]
    numeric_values = [value for value in numeric_values if value is not None]
    if len(numeric_values) > 1:
        return False
    if any(_is_terminal_hs_cell(cell) for cell in normalized[2:]):
        return False
    descriptive_cells = [
        cell
        for cell in normalized[1:]
        if re.search(r"[A-Za-zА-Яа-яЁё]{2,}", str(cell or ""))
    ]
    return len(descriptive_cells) >= 2


def _merge_split_candidate_line(lines: list[str], idx: int) -> tuple[str, int]:
    line = lines[idx]
    if "|" not in line or idx + 1 >= len(lines):
        return line, 0

    head_cells = _table_cells(line)
    for lookahead in (1, 2, 3, 4):
        if idx + lookahead >= len(lines):
            break
        skipped = lines[idx + 1 : idx + lookahead]
        if skipped and not all(_looks_like_merge_gap_noise(candidate) for candidate in skipped):
            continue

        next_line = lines[idx + lookahead]
        tail_cells = _table_cells(next_line)
        if _looks_like_split_item_head(head_cells) and _looks_like_split_numeric_tail(tail_cells):
            return _merge_split_item_lines(line, next_line), lookahead
        if _looks_like_repeated_item_numeric_continuation(head_cells, tail_cells):
            return _merge_repeated_item_continuation_lines(line, next_line), lookahead
    return line, 0


def _try_promote_positionless_companion(
    lines: list[str],
    idx: int,
    cells: list[str],
) -> dict | None:
    if idx + 1 >= len(lines):
        return None

    positionless_marker_item = _extract_positionless_marker_hs_last_item(cells)
    if positionless_marker_item is None:
        return None

    next_line = lines[idx + 1]
    if not _is_table_item_line(next_line):
        return None

    next_cells = _table_cells(next_line)
    next_position = _extract_position_from_cells(next_cells)
    normalized_next_cells = list(next_cells)
    if (
        len(normalized_next_cells) >= 2
        and _is_marker_like_cell(normalized_next_cells[0])
        and _is_article_like_cell(normalized_next_cells[1])
    ):
        normalized_next_cells = [
            _normalized_article_digits(normalized_next_cells[1]) or normalized_next_cells[1],
            *normalized_next_cells[2:],
        ]

    next_item = _parse_item_from_cells(normalized_next_cells, next_position)
    if (
        next_position is None
        or next_item is None
        or not _positionless_companion_matches_item(positionless_marker_item, next_item)
    ):
        return None

    promoted_item = dict(positionless_marker_item)
    promoted_item["position"] = next_position
    part_no = _extract_part_no_from_cells(next_cells)
    if part_no:
        promoted_item["part_no"] = part_no
    return promoted_item


def _normalize_positioned_cells(cells: list[str]) -> tuple[list[str], int | None]:
    normalized_cells = list(cells)
    if (
        len(normalized_cells) >= 2
        and not _has_explicit_pos_part_no_layout(normalized_cells)
        and _is_marker_like_cell(normalized_cells[0])
        and _is_article_like_cell(normalized_cells[1])
    ):
        normalized_article = _normalized_article_digits(normalized_cells[1])
        normalized_cells = [normalized_article or normalized_cells[1], *normalized_cells[2:]]

    normalized_article = _normalized_article_digits(normalized_cells[0])
    if normalized_article is not None:
        normalized_cells[0] = normalized_article
        position_digits = normalized_article
    else:
        position_digits = re.sub(r"\D", "", normalized_cells[0])

    if not position_digits:
        return normalized_cells, None

    position = int(position_digits)
    if position <= 0:
        position = None
    return normalized_cells, position


def _attach_part_no(item: dict | None, cells: list[str]) -> dict | None:
    if item is None:
        return None

    part_no = _extract_part_no_from_cells(cells)
    if not part_no:
        return item

    out = dict(item)
    out["part_no"] = part_no
    return out


def _extract_line_item(line: str, *, lines: list[str], idx: int) -> dict | None:
    line = _trim_item_line(line)
    cells = _table_cells(line)
    line_is_item = _is_table_item_line(line)
    if not line_is_item and (len(cells) < 4 or len(cells) > 6):
        return _try_promote_positionless_companion(lines, idx, cells)
    if line_is_item and len(cells) < 5:
        return None

    cells, position = _normalize_positioned_cells(cells)
    if line_is_item and len(cells) < 5:
        return None
    if any(_LEADING_NOISE_RE.search(str(cell or "")) for cell in cells[:3]):
        return None
    if position is None and not re.sub(r"\D", "", cells[0]):
        return None

    if not line_is_item:
        return _attach_part_no(_extract_partial_hs_companion_item(cells, position), cells)

    item = _parse_item_from_cells(cells, position)
    if item is not None:
        return _attach_part_no(item, cells)

    return _attach_part_no(_extract_loose_hs_tail_item(cells, position), cells)


def extract_structured_pipe_items(cleaned_context: str) -> list[dict]:
    if not cleaned_context:
        return []

    body = cleaned_context.split("=== INVOICE CONTENT ===\n", 1)[-1]
    parsed_items: list[dict] = []

    lines = body.splitlines()
    pending_repeated_heads: dict[tuple[str, str], str] = {}
    idx = 0
    while idx < len(lines):
        line, merged_tail_span = _merge_split_candidate_line(lines, idx)
        if not merged_tail_span:
            line_cells = _table_cells(line)
            pending_key = _repeated_item_merge_key(line_cells)
            if pending_key is not None:
                pending_head = pending_repeated_heads.get(pending_key)
                if pending_head is not None and _looks_like_repeated_item_numeric_continuation(
                    _table_cells(pending_head),
                    line_cells,
                ):
                    line = _merge_repeated_item_continuation_lines(pending_head, line)
                    pending_repeated_heads.pop(pending_key, None)
        item = _extract_line_item(line, lines=lines, idx=idx)
        if item is not None:
            parsed_items.append(item)
        elif not merged_tail_span:
            line_cells = _table_cells(line)
            pending_key = _repeated_item_merge_key(line_cells)
            if pending_key is not None and _looks_like_pending_repeated_item_head(line_cells):
                pending_repeated_heads[pending_key] = line
        idx += merged_tail_span + 1 if merged_tail_span else 1

    return parsed_items
