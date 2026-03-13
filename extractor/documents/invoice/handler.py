from __future__ import annotations

from typing import Any

from ...pipeline import run_invoice_extraction
from ..base import DocumentFieldSchema, DocumentHandler, DocumentSchema


class InvoiceHandler(DocumentHandler):
    document_code = "04021"
    label = "Invoice"
    schema = DocumentSchema(
        result_type="table",
        fields=(
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("country_sender", "Country Sender"),
        ),
        item_fields=(
            DocumentFieldSchema("position", "Position", kind="integer"),
            DocumentFieldSchema("description", "Description"),
            DocumentFieldSchema("hs_code", "HS Code"),
            DocumentFieldSchema("quantity", "Quantity", kind="number"),
            DocumentFieldSchema("unit", "Unit"),
            DocumentFieldSchema("cost", "Cost", kind="number"),
            DocumentFieldSchema("price", "Price", kind="number"),
            DocumentFieldSchema("currency_code", "Currency Code"),
            DocumentFieldSchema("currency_name", "Currency Name"),
            DocumentFieldSchema("document_date", "Document Date"),
            DocumentFieldSchema("document_number", "Document Number"),
            DocumentFieldSchema("country_origin", "Country Origin"),
            DocumentFieldSchema("country_origin_code", "Country Origin Code", kind="integer"),
            DocumentFieldSchema("country_sender", "Country Sender"),
        ),
    )

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
