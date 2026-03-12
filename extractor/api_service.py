from .constants import DOCUMENT_CODE_04021
from .pipeline import run_invoice_extraction


def validate_document_code(document_code: str) -> str:
    if document_code != DOCUMENT_CODE_04021:
        raise ValueError(
            f"This service only handles document_code '{DOCUMENT_CODE_04021}'. "
            f"Got '{document_code}'."
        )
    return document_code


def execute_extraction_request(
    *,
    document_code: str,
    ocr_draft: str,
    model: str | None = None,
) -> dict:
    validate_document_code(document_code)
    output = run_invoice_extraction(ocr_draft, model_id=model or None)

    metrics = output.get("metrics", {})
    model_id_used = output.get("model_id", "")
    if "error" in output:
        return {
            "status": "failed",
            "document_code": document_code,
            "model_id": model_id_used,
            "items": [],
            "count": 0,
            "metrics": metrics,
            "error": output["error"],
        }

    result = output.get("result", {})
    items = result.get("items", [])
    return {
        "status": "success",
        "document_code": document_code,
        "model_id": model_id_used,
        "items": items,
        "count": len(items),
        "metrics": metrics,
        "error": "",
    }
