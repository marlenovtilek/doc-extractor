"""Simple invoice JSON validation — like Dify."""

import json
import re
from typing import Any


def validate_invoice_json(text: str) -> dict[str, Any]:
    """
    Validate and parse invoice JSON from LLM response.
    
    Returns:
        {
            "is_valid": 0 or 1,
            "error": "" or error message,
            "items": [...],
            "count": int
        }
    """
    if not text:
        return {"is_valid": 0, "error": "Empty response", "items": [], "count": 0}
    
    # 1. Clean markdown
    clean = re.sub(r'```json|```', '', text).strip()
    
    # 2. Extract JSON array
    match = re.search(r'\[.*\]', clean, re.DOTALL)
    if match:
        clean = match.group()
    
    # 3. Parse JSON
    try:
        items = json.loads(clean)
    except json.JSONDecodeError as e:
        return {"is_valid": 0, "error": f"Invalid JSON: {e}", "items": [], "count": 0}
    
    # 4. Validate structure
    if not isinstance(items, list):
        return {"is_valid": 0, "error": "Root must be JSON array", "items": [], "count": 0}
    
    # 5. Filter items with valid description
    valid_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        
        description = item.get("description", "")
        if description and str(description).strip().lower() not in ("none", "null", ""):
            valid_items.append(item)
    
    if not valid_items:
        return {"is_valid": 0, "error": "No valid items found", "items": [], "count": 0}
    
    return {
        "is_valid": 1,
        "error": "",
        "items": valid_items,
        "count": len(valid_items),
    }


def extract_header_fields(items: list[dict]) -> dict[str, Any]:
    """
    Extract header fields from invoice items.
    
    Fields: document_number, document_date, currency_code, currency_name, country_sender
    """
    fields = {
        "document_number": None,
        "document_date": None,
        "currency_code": None,
        "currency_name": None,
        "country_sender": None,
    }
    
    for item in items:
        for key in fields:
            if fields[key] is None:
                value = item.get(key)
                if value and str(value).strip().lower() not in ("none", "null", ""):
                    fields[key] = value
    
    return fields
