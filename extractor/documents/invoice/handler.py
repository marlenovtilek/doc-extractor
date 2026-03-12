from __future__ import annotations

from typing import Any

from ...pipeline import run_invoice_extraction
from ..base import DocumentHandler


class InvoiceHandler(DocumentHandler):
    document_code = "04021"
    result_type = "table"

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
