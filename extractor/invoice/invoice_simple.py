"""Simple invoice extraction — Dify-style, single LLM call.

Optimized for speed:
- Gemini: 20-30s with timeout
- Cerebras: 5-10s (fastest)
- Ollama: 15-20s (local)
"""

import json
import time
import logging
import urllib.request
from typing import Any

from .invoice_prompt import INVOICE_SYSTEM_PROMPT
from extractor.providers import ModelTarget, resolve_model_target
from extractor.currency import load_currency_db
from .invoice_validator import validate_invoice_json, extract_header_fields

logger = logging.getLogger(__name__)


def clean_invoice_text(ocr_draft: str) -> str:
    """Simple OCR cleanup — remove noise, normalize whitespace."""
    if not ocr_draft:
        return ""

    import re
    text = ocr_draft.replace('\r', '')
    text = re.sub(r'\n{3,}', '\n\n', text)

    lines = []
    for line in text.split('\n'):
        clean_line = re.sub(r'[ \t]+', ' ', line).strip()
        if clean_line:
            lines.append(clean_line)

    return '\n'.join(lines)


def _call_gemini(prompt: str, model_id: str, api_key: str, timeout: int = 90) -> str:

    # Google API требует формат "gemini-1.5-flash" или "gemini-1.5-pro"
    # Очищаем модель от префиксов
    m_name = model_id.split("::")[-1] if "::" in model_id else model_id
    if m_name == "gemini" or not m_name:
        m_name = "gemini-1.5-flash"

    # Исправленный URL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json"
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"Gemini API Error ({m_name}): {e}")
        raise

def _call_cerebras(prompt: str, model_id: str, api_key: str, timeout: int = 30) -> str:
    """
    Direct Cerebras API call (fastest option).
    
    Args:
        prompt: Full extraction prompt
        model_id: Model name (e.g., 'llama3.1-8b')
        api_key: Cerebras API key
        timeout: Request timeout in seconds
    
    Returns:
        Raw text response from Cerebras
    """
    from cerebras.cloud.sdk import Cerebras
    
    try:
        client = Cerebras(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "You are an invoice data extraction expert. Return ONLY valid JSON array."},
                {"role": "user", "content": prompt[:100000]},  # Truncate if too long
            ],
            temperature=0,
            max_tokens=4096,
        )
        
        return response.choices[0].message.content or ""
        
    except Exception as e:
        logger.error(f"Cerebras API error: {e}")
        raise


def _call_ollama(prompt: str, model_id: str, base_url: str, timeout: int = 120) -> str:
    import urllib.request
    import urllib.error
    import json
    
    try:
        payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "format": "json", # 🔥 Принудительный JSON (ускоряет работу Qwen)
            "options": {
                "temperature": 0,
                "num_predict": 8192,
                "num_ctx": 32768, # 🔥 Увеличиваем контекст (по дефолту он 2048)
            },
            "keep_alive": "10m"   # 🔥 Оставляем модель в VRAM для быстрых следующих чанков
        }
        
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "[]")
            
    except urllib.error.URLError as e:
        logger.error(f"Ollama connection error (check SSH tunnel): {e}")
        raise ConnectionError(f"Cannot connect to Ollama at {base_url}. Is SSH tunnel running?") from e


def extract_invoice_simple(
    ocr_draft: str,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Extract invoice items with optimized LLM call.
    
    Auto-selects provider based on model string:
    - 'gemini', 'gemini-flash' → Gemini API (20-30s)
    - 'cerebras' → Cerebras API (5-10s, fastest)
    - 'ollama::model' → Ollama API (15-20s, local)
    
    Args:
        ocr_draft: Raw OCR text from invoice
        model: Model selector ('gemini', 'cerebras', 'ollama::qwen3:14b')
    
    Returns:
        {
            "fields": {...},  # Header fields
            "items": [...],   # Invoice items
            "count": int,     # Number of items
            "duration": float # Processing time in seconds
        }
    """
    t_start = time.perf_counter()
    
    # 1. Clean OCR text
    cleaned = clean_invoice_text(ocr_draft)
    if not cleaned:
        return {"error": "Empty OCR text", "items": [], "count": 0}
    
    # 2. Load currency database
    currency_db = load_currency_db()
    
    # 3. Build prompt
    prompt = INVOICE_SYSTEM_PROMPT.format(
        currency_db=json.dumps(currency_db, ensure_ascii=False),
        ocr_text=cleaned,
    )
    
    # 4. Resolve model and call appropriate API
    try:
        from extractor.runtime import get_runtime_settings
        runtime = get_runtime_settings()
        
        # Determine provider from model string
        model_str = (model or runtime.llm_model_primary).lower().strip()
        
        if model_str.startswith('ollama'):
            # Ollama: ollama::qwen3:14b or ollama::qwen3.5:14b
            if '::' in model_str:
                model_id = model_str.split('::')[1]
            else:
                model_id = runtime.ollama_model_default or 'qwen3:14b'
            
            base_url = runtime.ollama_base_url or 'http://127.0.0.1:11434'
            logger.info(f"Using Ollama: {model_id} at {base_url}")
            raw_output = _call_ollama(prompt, model_id, base_url, timeout=120)
            
        elif model_str == 'cerebras' or 'cerebras' in model_str:
            # Cerebras: fastest option (5-10s)
            model_id = runtime.cerebras_model or 'llama3.1-8b'
            api_key = runtime.cerebras_api_key
            logger.info(f"Using Cerebras: {model_id}")
            raw_output = _call_cerebras(prompt, model_id, api_key, timeout=30)
            
        else:
            # Gemini: default fallback
            model_id = 'gemini-2.5-flash' if 'flash' in model_str else 'gemini-2.5-pro'
            api_key = runtime.gemini_api_key
            logger.info(f"Using Gemini: {model_id}")
            raw_output = _call_gemini(prompt, model_id, api_key, timeout=90)
        
        usage = {}
        
    except TimeoutError as e:
        logger.error(f"LLM timeout: {e}")
        return {"error": f"LLM timeout: {e}", "items": [], "count": 0}
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        return {"error": str(e), "items": [], "count": 0}
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return {"error": f"LLM failed: {e}", "items": [], "count": 0}
    
    # 5. Validate JSON response
    validation = validate_invoice_json(raw_output)
    
    if not validation["is_valid"]:
        logger.warning(f"Validation failed: {validation['error']}")
        return {
            "error": validation["error"],
            "items": [],
            "count": 0,
        }
    
    # 6. Extract header fields from items
    fields = extract_header_fields(validation["items"])
    
    # 7. Build result
    duration = round(time.perf_counter() - t_start, 3)
    logger.info(f"Extraction complete: {validation['count']} items in {duration:.2f}s")
    
    return {
        "fields": fields,
        "items": validation["items"],
        "count": validation["count"],
        "duration": duration,
        "usage": usage,
    }


def _call_openai(prompt_sys: str, prompt_user: str, model_id: str, api_key: str, timeout: int = 90) -> str:
    """
    Direct OpenAI API call (используется как Fallback).
    Работает через встроенный urllib, чтобы не тянуть лишние зависимости.
    """
    import urllib.request
    import urllib.error
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": prompt_sys},
                {"role": "user", "content": prompt_user}
            ],
            "temperature": 0
        }
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST",
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result["choices"][0]["message"]["content"]
            
    except urllib.error.URLError as e:
        logger.error(f"OpenAI connection error: {e}")
        raise ConnectionError(f"Cannot connect to OpenAI API") from e
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise