from __future__ import annotations

from datetime import datetime
import html
import re
import time
from typing import Any

import langextract as lx

from .base import DocumentFieldSchema, DocumentHandler, DocumentSchema
from ..metrics import RunMetrics, timer
from ..providers import extract_with_langextract_entities, resolve_model_target
from ..runtime import get_runtime_settings


CONTRACT_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Contract document in English. The text may have mixed
formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the contract
- `document_date` — the date of the contract
- `parties` — the parties involved; emit one extraction per party
- `subject` — the subject, object, or purpose of the contract
- `description` — a concise summary of the contract in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and decorative boilerplate.
- Normalize dates when possible.
- Remove formatting artifacts mentally; do not copy broken punctuation unless it is
  part of an actual identifier.
- If a field cannot be found, do not hallucinate it.
- For `parties`, emit separate extractions of class `parties` for each party.
- Return only relevant extractions.
"""

CONTRACT_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "CONTRACT No. CT-2024/117\n"
            "Date: 12 November 2024\n"
            "This contract is made between Acme GmbH, Germany and Global Tech LLC, Kyrgyz Republic.\n"
            "Subject: Supply of industrial spare parts.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "CT-2024/117"),
            lx.data.Extraction("document_date", "12/11/2024"),
            lx.data.Extraction("parties", "Acme GmbH"),
            lx.data.Extraction("parties", "Global Tech LLC"),
            lx.data.Extraction("subject", "Supply of industrial spare parts"),
            lx.data.Extraction(
                "description",
                "Контракт на поставку промышленных запасных частей между Acme GmbH и Global Tech LLC.",
            ),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Agreement Ref. SC-88/25\n"
            "Signed on 05/03/2025\n"
            "Parties: Sennheiser Middle East FZE (Seller) and OOO Global Tech (Buyer).\n"
            "The purpose of this contract is the sale and delivery of professional audio equipment.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "SC-88/25"),
            lx.data.Extraction("document_date", "05/03/2025"),
            lx.data.Extraction("parties", "Sennheiser Middle East FZE"),
            lx.data.Extraction("parties", "OOO Global Tech"),
            lx.data.Extraction("subject", "Sale and delivery of professional audio equipment"),
            lx.data.Extraction(
                "description",
                "Контракт на продажу и поставку профессионального аудиооборудования.",
            ),
        ],
    ),
]

SUPPLY_CONTRACT_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Supply Contract document in English. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, identifier, or INN-like
  contract identifier when it is the only stable identifier in the document
- `document_date` — the date of the contract
- `description` — a concise summary of the contract in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

SUPPLY_CONTRACT_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "SUPPLY CONTRACT No. SUP-77/24\n"
            "Date: 14 September 2024\n"
            "This supply contract covers the delivery of industrial lubricants and spare parts.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "SUP-77/24"),
            lx.data.Extraction("document_date", "14/09/2024"),
            lx.data.Extraction(
                "description",
                "Договор поставки промышленных смазочных материалов и запасных частей.",
            ),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Supply Agreement Ref. INN-5568021\n"
            "Signed on 05/03/2025\n"
            "The contract is for supply of professional audio equipment.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "INN-5568021"),
            lx.data.Extraction("document_date", "05/03/2025"),
            lx.data.Extraction(
                "description",
                "Договор поставки профессионального аудиооборудования.",
            ),
        ],
    ),
]

POWER_OF_ATTORNEY_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Power of Attorney (POA) document in English. The
text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the numbering or reference number of the POA
- `authorized_person` — full name of the person who is authorized to act
- `trusted_person` — full name of the person who issued the POA or grants the authority
- `document_date` — the date of the POA
- `description` — the type of document, keep it in Russian

# RULES
- Ignore headers, footers, signatures, stamps, and legal boilerplate not related
  to the requested fields.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- If `document_date` is not found, default it to the current date.
- Return only relevant extractions.
"""

POWER_OF_ATTORNEY_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "POWER OF ATTORNEY No. POA-22/2025\n"
            "Date: 03 February 2025\n"
            "Global Tech LLC hereby authorizes Aibek Omuraliev to represent the company.\n"
            "Granted by Dinara Sadykova, General Director.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "POA-22/2025"),
            lx.data.Extraction("authorized_person", "Aibek Omuraliev"),
            lx.data.Extraction("trusted_person", "Dinara Sadykova"),
            lx.data.Extraction("document_date", "03/02/2025"),
            lx.data.Extraction("description", "Доверенность"),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Special Power of Attorney\n"
            "Issued on 18/10/2024\n"
            "Acme GmbH appoints Elena Petrova as authorized representative.\n"
            "Signed by Markus Klein.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", None),
            lx.data.Extraction("authorized_person", "Elena Petrova"),
            lx.data.Extraction("trusted_person", "Markus Klein"),
            lx.data.Extraction("document_date", "18/10/2024"),
            lx.data.Extraction("description", "Доверенность"),
        ],
    ),
]

TRUSTED_PASSPORT_POA_EXTRACTION_PROMPT = """
# ROLE
You are an expert legal-document data extractor.

# TASK
You are given OCR text from a Power of Attorney (POA) document in English. The
text may have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the numbering or reference number of the POA
- `authorized_person` — full name of the person who is authorized to act
- `trusted_person` — full name of the person who issued the POA or grants the authority
- `document_date` — the date of the POA
- `description` — document type; when passport details of a natural person are
  present in the text, use `Power of Attorney with trusted persons passport`

# RULES
- Ignore headers, footers, signatures, stamps, and legal boilerplate not related
  to the requested fields.
- Normalize dates when possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- If `document_date` is not found, default it to the current date.
- Return only relevant extractions.
"""

TRUSTED_PASSPORT_POA_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "POWER OF ATTORNEY No. TP-14/2025\n"
            "Issued on 21/01/2025\n"
            "Aizada Toktorova authorizes Bekzat Imanov to act on her behalf.\n"
            "Passport No. AN1234567 issued to Bekzat Imanov.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "TP-14/2025"),
            lx.data.Extraction("authorized_person", "Bekzat Imanov"),
            lx.data.Extraction("trusted_person", "Aizada Toktorova"),
            lx.data.Extraction("document_date", "21/01/2025"),
            lx.data.Extraction("description", "Power of Attorney with trusted persons passport"),
        ],
    ),
]

CMR_EXTRACTION_PROMPT = """
# ROLE
You are an expert logistics-document data extractor.

# TASK
You are given OCR text from a CMR document. The text may have mixed formats,
irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, or identifier of the CMR
- `document_date` — the date of the document
- `description` — a concise summary of the document in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

CMR_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "CMR No. 442190\n"
            "Date: 18/09/2025\n"
            "International consignment note for delivery of industrial equipment from Germany to Kyrgyzstan.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "442190"),
            lx.data.Extraction("document_date", "18/09/2025"),
            lx.data.Extraction(
                "description",
                "Международная транспортная накладная CMR на перевозку промышленного оборудования.",
            ),
        ],
    ),
]

STI025_EXTRACTION_PROMPT = """
# ROLE
You are an expert registration-document data extractor.

# TASK
You are given OCR text from a Taxpayer Registration Card STI-025. The text may
have mixed formats, irregular structure, and OCR artifacts.

Extract the following fields:
- `document_number` — the official number, reference, identifier, or INN-like registration number
- `document_date` — the date of the document
- `description` — a concise summary of the document in Russian (1–2 sentences)

# RULES
- Ignore headers, footers, signatures, stamps, and irrelevant boilerplate text.
- Normalize dates whenever possible.
- Remove decorative symbols, repeated whitespace, and formatting artifacts.
- If a field cannot be found, set it to null.
- Return only relevant extractions.
"""

STI025_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Taxpayer Registration Card STI-025\n"
            "INN: 12345678901234\n"
            "Issued on 07.11.2024\n"
            "Registration card confirming taxpayer registration.\n"
        ),
        extractions=[
            lx.data.Extraction("document_number", "12345678901234"),
            lx.data.Extraction("document_date", "07/11/2024"),
            lx.data.Extraction(
                "description",
                "Карточка регистрации налогоплательщика формы STI-025.",
            ),
        ],
    ),
]

TRACKED_CONTRACT_FIELDS = (
    "document_number",
    "document_date",
    "parties",
    "subject",
    "description",
)

TRACKED_SUPPLY_CONTRACT_FIELDS = (
    "document_number",
    "document_date",
    "description",
)

TRACKED_POWER_OF_ATTORNEY_FIELDS = (
    "document_number",
    "authorized_person",
    "trusted_person",
    "document_date",
    "description",
)

TRACKED_SIMPLE_DOCUMENT_FIELDS = (
    "document_number",
    "document_date",
    "description",
)


def clean_contract_text(ocr_draft: str) -> str:
    """Normalize OCR text for object-style legal extraction."""
    text = html.unescape(ocr_draft or "")
    if not text.strip():
        return ""

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(p|div|span|table|tbody|thead|tr|td|th)\b[^>]*>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("**", " ")

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t|")
        if not line:
            continue
        if lines and line == lines[-1]:
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def normalize_contract_date(value: str | None) -> str | None:
    """Normalize a date into DD/MM/YYYY when possible."""
    text = (value or "").strip()
    if not text:
        return None

    direct_formats = (
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
    )
    for fmt in direct_formats:
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue

    compact = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if compact:
        day, month, year = compact.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"

    return text


def aggregate_object_fields(
    extractions: list[dict[str, object]],
    tracked_fields: tuple[str, ...],
    *,
    array_fields: tuple[str, ...] = (),
    default_current_date_if_missing: bool = False,
) -> dict[str, object]:
    """Aggregate LangExtract entities into a single object-style document."""
    fields: dict[str, object] = {name: None for name in tracked_fields}
    arrays: dict[str, list[str]] = {name: [] for name in array_fields}

    for extraction in extractions:
        extraction_class = str(extraction.get("extraction_class") or "").strip()
        extraction_text = str(extraction.get("extraction_text") or "").strip()
        if not extraction_class or not extraction_text:
            continue

        if extraction_class in arrays:
            if extraction_text not in arrays[extraction_class]:
                arrays[extraction_class].append(extraction_text)
            continue

        if extraction_class in fields and not fields[extraction_class]:
            fields[extraction_class] = extraction_text

    if "document_date" in fields:
        normalized_date = normalize_contract_date(fields.get("document_date"))  # type: ignore[arg-type]
        if normalized_date is None and default_current_date_if_missing:
            normalized_date = datetime.now().strftime("%d/%m/%Y")
        fields["document_date"] = normalized_date

    for name, values in arrays.items():
        fields[name] = values or None
    return fields


def validate_object_fields(
    fields: dict[str, object],
    tracked_fields: tuple[str, ...],
    *,
    array_fields: tuple[str, ...] = (),
    empty_error: str,
) -> tuple[bool, str]:
    """Validate a normalized object-style document."""
    if not fields:
        return False, empty_error

    if not any(fields.get(name) for name in tracked_fields):
        return False, empty_error

    for key in array_fields:
        value = fields.get(key)
        if value is not None:
            if not isinstance(value, list):
                return False, f"'{key}' must be a list or null"
            if any(not isinstance(item, str) for item in value):
                return False, f"'{key}' must contain only strings"

    for key in tracked_fields:
        if key in array_fields:
            continue
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            return False, f"'{key}' must be a string or null"

    return True, ""


def compute_object_field_fill_rates(
    fields: dict[str, object],
    tracked_fields: tuple[str, ...],
) -> dict[str, float]:
    """Return per-field fill rates for object-style extraction."""
    rates: dict[str, float] = {}
    for name in tracked_fields:
        value = fields.get(name)
        if isinstance(value, list):
            rates[name] = 1.0 if value else 0.0
        else:
            rates[name] = 1.0 if value not in (None, "", "null", "none") else 0.0
    return rates


def aggregate_contract_fields(extractions: list[dict[str, object]]) -> dict[str, object]:
    return aggregate_object_fields(
        extractions,
        TRACKED_CONTRACT_FIELDS,
        array_fields=("parties",),
    )


def validate_contract_fields(fields: dict[str, object]) -> tuple[bool, str]:
    return validate_object_fields(
        fields,
        TRACKED_CONTRACT_FIELDS,
        array_fields=("parties",),
        empty_error="No contract fields extracted",
    )


def compute_contract_field_fill_rates(fields: dict[str, object]) -> dict[str, float]:
    return compute_object_field_fill_rates(fields, TRACKED_CONTRACT_FIELDS)


def _resolve_object_model(model_id: str | None, *, label: str):
    runtime = get_runtime_settings()
    primary_model = resolve_model_target(model_id)
    if primary_model.provider != "cerebras":
        return primary_model, False

    fallback_model = resolve_model_target(runtime.llm_model_fallback)
    if fallback_model.provider == "cerebras":
        raise ValueError(
            f"{label} extraction requires a LangExtract-backed model "
            "(gemini, openai, or ollama)."
        )
    return fallback_model, True


def _run_object_document_extraction(
    ocr_draft: str,
    *,
    model_id: str | None,
    prompt: str,
    examples: list[lx.data.ExampleData],
    tracked_fields: tuple[str, ...],
    array_fields: tuple[str, ...] = (),
    default_current_date_if_missing: bool = False,
    empty_error: str,
    label: str,
) -> dict:
    """Shared object-style extraction flow for legal documents."""
    metrics = RunMetrics()
    t_wall_start = time.perf_counter()

    with timer() as t_clean:
        context = clean_contract_text(ocr_draft)
    metrics.t_clean_s = t_clean[0]

    target_model, implicit_fallback = _resolve_object_model(model_id, label=label)
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
            prompt_description=prompt,
            examples=examples,
        )
    metrics.t_primary_llm_s = t_llm[0]
    if usage:
        metrics.token_usage["primary"] = usage

    with timer() as t_validate:
        fields = aggregate_object_fields(
            extractions,
            tracked_fields,
            array_fields=array_fields,
            default_current_date_if_missing=default_current_date_if_missing,
        )
        is_valid, error = validate_object_fields(
            fields,
            tracked_fields,
            array_fields=array_fields,
            empty_error=empty_error,
        )
    metrics.t_validate_s = t_validate[0]
    metrics.primary_valid = is_valid

    if not is_valid:
        metrics.t_total_s = time.perf_counter() - t_wall_start
        return {
            "error": error or f"{label} extraction failed",
            "metrics": metrics.to_dict(),
            "model_id": target_model.model_id,
        }

    metrics.field_fill_rates = compute_object_field_fill_rates(fields, tracked_fields)
    metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

    return {
        "result": {"fields": fields, "items": [], "count": 0},
        "metrics": metrics.to_dict(),
        "model_id": target_model.model_id,
    }


def run_contract_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '03011'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=CONTRACT_EXTRACTION_PROMPT,
        examples=CONTRACT_EXAMPLES,
        tracked_fields=TRACKED_CONTRACT_FIELDS,
        array_fields=("parties",),
        empty_error="No contract fields extracted",
        label="Generic contract",
    )


def run_supply_contract_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '00012'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=SUPPLY_CONTRACT_EXTRACTION_PROMPT,
        examples=SUPPLY_CONTRACT_EXAMPLES,
        tracked_fields=TRACKED_SUPPLY_CONTRACT_FIELDS,
        empty_error="No supply contract fields extracted",
        label="Supply contract",
    )


def run_power_of_attorney_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '11019'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=POWER_OF_ATTORNEY_EXTRACTION_PROMPT,
        examples=POWER_OF_ATTORNEY_EXAMPLES,
        tracked_fields=TRACKED_POWER_OF_ATTORNEY_FIELDS,
        default_current_date_if_missing=True,
        empty_error="No power of attorney fields extracted",
        label="Power of attorney",
    )


def run_trusted_passport_poa_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '000011'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=TRUSTED_PASSPORT_POA_EXTRACTION_PROMPT,
        examples=TRUSTED_PASSPORT_POA_EXAMPLES,
        tracked_fields=TRACKED_POWER_OF_ATTORNEY_FIELDS,
        default_current_date_if_missing=True,
        empty_error="No power of attorney with trusted persons passport fields extracted",
        label="Power of attorney with trusted persons passport",
    )


def run_cmr_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '00002'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=CMR_EXTRACTION_PROMPT,
        examples=CMR_EXAMPLES,
        tracked_fields=TRACKED_SIMPLE_DOCUMENT_FIELDS,
        empty_error="No CMR fields extracted",
        label="CMR",
    )


def run_sti025_extraction(ocr_draft: str, model_id: str | None = None) -> dict:
    """Full pipeline for document_code == '000004'."""
    return _run_object_document_extraction(
        ocr_draft,
        model_id=model_id,
        prompt=STI025_EXTRACTION_PROMPT,
        examples=STI025_EXAMPLES,
        tracked_fields=TRACKED_SIMPLE_DOCUMENT_FIELDS,
        empty_error="No STI-025 fields extracted",
        label="Taxpayer Registration Card STI-025",
    )


class _BaseObjectHandler(DocumentHandler):
    """Thin adapter to expose object-style pipelines through the registry."""

    def _empty_fields(self) -> dict[str, object]:
        return {field.name: None for field in self.schema.fields}

    def _wrap_object_output(self, output: dict[str, Any]) -> dict[str, Any]:
        metrics = output.get("metrics", {})
        model_id = output.get("model_id", "")

        if "error" in output:
            return {
                "error": output["error"],
                "metrics": metrics,
                "model_id": model_id,
                "result_type": self.result_type,
                "data": {"fields": self._empty_fields(), "items": [], "count": 0},
            }

        result = output.get("result", {})
        fields = result.get("fields", self._empty_fields())
        return {
            "metrics": metrics,
            "model_id": model_id,
            "result_type": self.result_type,
            "data": {
                "fields": fields,
                "items": [],
                "count": 0,
            },
        }


class ContractHandler(_BaseObjectHandler):
    document_code = "03011"
    label = "Contract"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("parties", "Parties", kind="array"),
            DocumentFieldSchema("subject", "Subject"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(run_contract_extraction(ocr_draft, model_id=model or None))


class SupplyContractHandler(_BaseObjectHandler):
    document_code = "00012"
    label = "Supply Contract"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(
            run_supply_contract_extraction(ocr_draft, model_id=model or None)
        )


class PowerOfAttorneyHandler(_BaseObjectHandler):
    document_code = "11019"
    label = "Power of Attorney"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("authorized_person", "Authorized Person"),
            DocumentFieldSchema("trusted_person", "Trusted Person"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(
            run_power_of_attorney_extraction(ocr_draft, model_id=model or None)
        )


class TrustedPassportPowerOfAttorneyHandler(_BaseObjectHandler):
    document_code = "000011"
    label = "PA with Trusted Persons Passport"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("authorized_person", "Authorized Person"),
            DocumentFieldSchema("trusted_person", "Trusted Person"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(
            run_trusted_passport_poa_extraction(ocr_draft, model_id=model or None)
        )


class CMRHandler(_BaseObjectHandler):
    document_code = "00002"
    label = "CMR"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(run_cmr_extraction(ocr_draft, model_id=model or None))


class TaxpayerRegistrationCardHandler(_BaseObjectHandler):
    document_code = "000004"
    label = "Taxpayer Registration Card STI-025"
    schema = DocumentSchema(
        result_type="object",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("description", "Description"),
        ),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        return self._wrap_object_output(run_sti025_extraction(ocr_draft, model_id=model or None))
