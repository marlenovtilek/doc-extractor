import logging
import time

from ..context.execution import (
    ensure_not_cancelled,
    report_progress,
)
from ..documents.registry import get_document_definition

logger = logging.getLogger(__name__)

def execute_extraction_request(
    *,
    document_code: str,
    ocr_draft: str,
    model: str | None = None,
    source_file_path: str | None = None,
) -> dict:
    """Центральная точка входа для всех запросов на извлечение."""
    t_start = time.perf_counter()
    
    report_progress("routing", "Выбор обработчика документа...")
    ensure_not_cancelled()
    
    # 1. Получаем определение документа из реестра
    try:
        definition = get_document_definition(document_code)
        handler = definition.handler
    except Exception as e:
        logger.error(f"Handler not found for {document_code}: {e}")
        return {
            "status": "failed",
            "document_code": document_code,
            "error": f"Unsupported document code: {document_code}",
            "data": {"items": [], "count": 0}
        }

    report_progress("extracting", f"Запуск анализа {definition.label}...")
    ensure_not_cancelled()

    # 2. Запускаем извлечение (Таймаут берется внутри хэндлера или провайдера)
    try:
        # Теперь просто передаем строку модели, хэндлер сам её разрешит через providers.py
        output = handler.extract(
            ocr_draft=ocr_draft,
            model=model,
            source_file_path=source_file_path,
        )
    except Exception as exc:
        logger.error(f"Extraction error: {exc}")
        return {
            "status": "failed",
            "document_code": document_code,
            "duration": round(time.perf_counter() - t_start, 3),
            "error": str(exc),
            "data": {"items": [], "count": 0},
        }

    ensure_not_cancelled()

    # 3. Возвращаем результат
    duration = round(time.perf_counter() - t_start, 3)
    
    # Если хэндлер вернул ошибку внутри
    if "error" in output and output["error"]:
        response = {
            "status": "failed",
            "document_code": document_code,
            "duration": duration,
            "error": output["error"],
            "data": output.get("data", {"items": [], "count": 0}),
        }
        for key in ("result_type", "model_id", "metrics"):
            if key in output:
                response[key] = output[key]
        return response

    response = {
        "status": "success",
        "document_code": document_code,
        "duration": duration,
        "error": "",
        "data": output.get("data", {}),
    }
    for key in ("result_type", "model_id", "metrics"):
        if key in output:
            response[key] = output[key]
    return response
