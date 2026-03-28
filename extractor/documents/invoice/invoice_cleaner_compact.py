from __future__ import annotations

from collections import Counter
import re


def normalize_item_schema(
    lines: list[str],
    *,
    is_table_item_line,
    table_cells,
    looks_like_article_cell,
    looks_like_marker_cell,
    trim_item_line,
) -> list[str]:
    item_lines = [line for line in lines if is_table_item_line(line)]
    if not item_lines:
        return lines

    article_leading = 0
    marker_prefixed = 0
    for line in item_lines:
        cells = table_cells(line)
        if not cells:
            continue
        if looks_like_article_cell(cells[0]):
            article_leading += 1
        elif len(cells) >= 2 and looks_like_marker_cell(cells[0]) and looks_like_article_cell(cells[1]):
            marker_prefixed += 1

    if article_leading < 5 or marker_prefixed < 1:
        return lines

    normalized = []
    for line in lines:
        if not is_table_item_line(line):
            normalized.append(line)
            continue

        cells = table_cells(line)
        if len(cells) >= 2 and looks_like_marker_cell(cells[0]) and looks_like_article_cell(cells[1]):
            line = "| " + " | ".join(cells[1:]) + " |"
        normalized.append(trim_item_line(line))

    return normalized


def compact_table_ocr(
    lines: list[str],
    *,
    is_pipe_table_line,
    is_table_item_line,
    looks_like_positionless_marker_companion_line,
    looks_like_pipe_noise,
    extract_inline_blob_pipe_rows,
    trim_item_line,
    looks_like_blob_noise,
    looks_like_boilerplate_line,
    boilerplate_key,
    normalize_item_schema,
) -> list[str]:
    compacted = []
    seen_boilerplate = set()

    for line in lines:
        if is_pipe_table_line(line):
            if looks_like_positionless_marker_companion_line(line):
                compacted.append(line)
                continue
            if looks_like_pipe_noise(line):
                continue
            if is_table_item_line(line):
                embedded_rows = extract_inline_blob_pipe_rows(line)
                line = trim_item_line(line)
                compacted.extend(embedded_rows)
            else:
                trimmed_line = trim_item_line(line)
                if trimmed_line != line and is_table_item_line(trimmed_line):
                    line = trimmed_line
            compacted.append(line)
            continue

        if looks_like_blob_noise(line):
            continue

        if looks_like_boilerplate_line(line):
            key = boilerplate_key(line)
            if key in seen_boilerplate:
                continue
            seen_boilerplate.add(key)

        compacted.append(line)

    return normalize_item_schema(compacted)


def looks_like_blob_noise(line: str, *, looks_like_boilerplate_line) -> bool:
    if looks_like_boilerplate_line(line):
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
