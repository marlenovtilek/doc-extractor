from __future__ import annotations

import re


def rehydrate_flattened_ocr_markdown(text: str) -> str:
    """
    Restore coarse line structure in OCR text that was flattened into a single
    blob. The goal is not perfect reconstruction, only enough structure for the
    pipe-table normalizer and parser to work reliably.
    """
    if not text:
        return ""

    text = text.replace("\r", "")
    text = re.sub(r"\s*(!\[[^\]]*\]\([^)]*\))\s*", r"\n\1\n", text)
    text = re.sub(r"(?<!\n)(?=##\s*)", "\n", text)

    break_patterns = (
        r"Page:",
        r"Date:",
        r"Invoice Number:",
        r"Customer No:",
        r"Customer VAT ID:",
        r"Shipment number:",
        r"Contact:",
        r"E-Mail:",
        r"Incoterms:",
        r"Order date:",
        r"Carry-Over:",
        r"Please beware:",
        r"Net w(?:eight| eight):",
        r"Value \(EUR\):",
        r"Total Amount \(EUR\):",
        r"Payment Terms:",
        r"IBAN:",
        r"BIC:",
        r"Sparkasse\b",
        r"Managing Director:",
        r"Amtsgericht\b",
        r"\|[ \t]*(?:POS|N[ºo])[ \t]*\|[ \t]*Part No[ \t]*\|",
        r"\|[ \t]*-----[-| \t]*\|",
        r"\|[ \t]*Carry-Over:[ \t]*\|",
        (
            r"\|[ \t]*(?:\d{1,4}|[+\-])(?:<br\s*/?>\d{1,4})?\s*\|[ \t]*"
            r"(?:\d{4,14}(?:<br\s*/?>\d{4,14})?\s*\|[ \t]*)?[A-Za-zА-Яа-яЁё]"
        ),
        r"\|[ \t]*\|[ \t]*Order date:",
    )
    for pattern in break_patterns:
        text = re.sub(rf"(?<!\n)(?={pattern})", "\n", text)

    text = re.sub(r"(?<!\n)(?=\d{1,2}/\d{1,2}(?:\s|$))", "\n", text)
    text = re.sub(
        r"(?<!\n)(?=(?:VAT\s*0[.,]00%:|Cash before Delivery\b))",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
