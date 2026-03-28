from __future__ import annotations

import html
import re


def normalize_pipe_table(text: str) -> str:
    text = re.sub(
        r"(?<!\n)(?="
        r"\|(?:[ \t]*\|){3}[ \t]*[+\-*•][ \t]*\|[ \t]*[А-Яа-яёЁA-Za-z]"
        r")",
        "\n",
        text,
    )
    text = re.sub(
        r"(?<!\n)(?="
        r"\|[ \t]*\|[ \t]*\d{1,3}(?:<br\s*/?>\d{1,3})+[ \t]*\|[ \t]*"
        r"\d{4,14}(?:<br\s*/?>\d{4,14})+[ \t]*\|"
        r")",
        "\n",
        text,
    )
    text = re.sub(
        r"(?<!\n)(?="
        r"\|[ \t]*\|[ \t]*(?:\d{1,8}|[+\-])[ \t]*\|[ \t]*"
        r"(?:"
        r"[А-Яа-яёЁA-Za-z]"
        r"|"
        r"\d{4,14}[ \t]*\|[ \t]*[А-Яа-яёЁA-Za-z]"
        r")"
        r")",
        "\n",
        text,
    )
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
    text = re.sub(
        r"(?<!\n)(?="
        r"\|[ \t]*(?:\d{1,3}[ \t]+\d{1,3}|\d{1,4}|[+\-])[ \t]*\|"
        r"(?:[ \t]*\|[ \t]*)+"
        r"(?:"
        r"[А-Яа-яёЁA-Za-z]"
        r"|"
        r"\d{4,14}[ \t]*\|(?:[ \t]*\|[ \t]*)*[А-Яа-яёЁA-Za-z]"
        r")"
        r")",
        "\n",
        text,
    )
    text = re.sub(
        r"(?m)^\|[ \t]*\|(?=[ \t]*(?:\d{1,8}|[+\-])\s*\|)",
        "|",
        text,
    )
    text = re.sub(
        r"(?m)^\|[ \t]*\|(?=[ \t]*\d{1,3}(?:<br\s*/?>\d{1,3})+\s*\|)",
        "|",
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
    sparse_row_start_re = re.compile(
        r"\|[ \t]*(?:\d{1,3}[ \t]+\d{1,3}|\d{1,8}|[+\-])[ \t]*\|"
        r"(?:[ \t]*\|[ \t]*)+"
        r"(?:"
        r"[А-Яа-яёЁA-Za-z]"
        r"|"
        r"\d{4,14}[ \t]*\|(?:[ \t]*\|[ \t]*)*[А-Яа-яёЁA-Za-z]"
        r")"
    )
    for line in text.split("\n"):
        starts = []
        for regex in (row_start_re, sparse_row_start_re):
            for match in regex.finditer(line):
                if any(abs(match.start() - start) < 20 for start in starts):
                    continue
                starts.append(match.start())
        starts.sort()
        if len(starts) <= 1:
            dense_lines.append(line)
            continue

        starts.append(len(line))
        for start, end in zip(starts, starts[1:]):
            part = line[start:end].strip()
            if part:
                dense_lines.append(part)

    return "\n".join(dense_lines)


def strip_markup_noise(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)</?(td|th)\b[^>]*>", " | ", text)
    text = re.sub(r"(?i)</?(tr|table|tbody|thead|p|div|span)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", "")
    return text
