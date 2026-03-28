from __future__ import annotations

import json
import re

import langextract as lx


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
