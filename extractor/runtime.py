import os
from dataclasses import dataclass
from functools import lru_cache
import re
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency in some environments
    def load_dotenv(*args, **kwargs):  # type: ignore[no-redef]
        return False

load_dotenv(override=False)

def _env_int(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)))
    except: return default


def _env_int_any(names: tuple[str, ...], default: int) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_model_list(raw: str) -> tuple[str, ...]:
    seen: set[str] = set()
    models: list[str] = []
    for part in re.split(r"[|,\n]", raw):
        value = part.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        models.append(value)
    return tuple(models)


def _env_model_list(name: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    parsed = _normalize_model_list(raw)
    return parsed

@dataclass(frozen=True)
class RuntimeSettings:
    # Ключи
    doc_extractor_api_token: str
    gemini_api_key: str
    openai_api_key: str
    cerebras_api_key: str
    vllm_api_key: str
    vlm_api_key: str
    
    # Роутинг моделей
    llm_model_primary: str
    llm_model_fallback: str

    # Каталоги моделей по провайдерам
    gemini_models: tuple[str, ...]
    gpt_models: tuple[str, ...]
    ollama_models: tuple[str, ...]
    cerebras_models: tuple[str, ...]
    vllm_models: tuple[str, ...]
    vlm_models: tuple[str, ...]

    # Параметры провайдеров
    cerebras_base_url: str
    ollama_base_url: str
    vllm_base_url: str
    vlm_base_url: str
    gemini_timeout_s: int
    openai_timeout_s: int
    cerebras_timeout_s: int
    ollama_timeout_s: int
    vllm_timeout_s: int
    vlm_timeout_s: int
    vllm_supports_large_context: bool
    vlm_pdf_render_dpi: int
    vlm_pages_per_prompt: int
    vlm_max_pages: int
    vlm_passes: int
    invoice_vlm_helper_model: str
    
    # Настройки чанкинга
    invoice_chunk_size_gemini: int
    invoice_chunk_size_openai: int
    invoice_chunk_size_ollama: int
    invoice_chunk_size_cerebras: int
    invoice_chunk_size_vllm: int
    invoice_vllm_max_workers: int
    invoice_chunk_overlap_default: int
    invoice_chunk_overlap_vllm: int
    chunk_size_default: int
    default_chunk_max_workers: int
    llm_max_char_buffer: int
    web_job_max_workers: int
    web_job_retention_s: int
    web_job_max_stored: int
    currency_db_json: str

@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        doc_extractor_api_token=os.getenv("DOC_EXTRACTOR_API_TOKEN", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
        vllm_api_key=os.getenv("VLLM_API_KEY", ""),
        vlm_api_key=os.getenv("VLM_API_KEY", ""),
        
        llm_model_primary=os.getenv("LLM_MODEL_PRIMARY", "gemini"),
        llm_model_fallback=os.getenv("LLM_MODEL_FALLBACK", "openai"),

        gemini_models=_env_model_list(
            "GEMINI_MODELS",
            (
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash",
            ),
        ),
        gpt_models=_env_model_list(
            "GPT_MODELS",
            (
                "gpt-4o-mini",
            ),
        ),
        ollama_models=_env_model_list(
            "OLLAMA_MODELS",
            (
                "qwen2.5:14b",
            ),
        ),
        cerebras_models=_env_model_list(
            "CEREBRAS_MODELS",
            (
                "llama3.1-8b",
            ),
        ),
        vllm_models=_env_model_list(
            "VLLM_MODELS",
            (),
        ),
        vlm_models=_env_model_list(
            "VLM_MODELS",
            (),
        ),

        cerebras_base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        vllm_base_url=os.getenv("VLLM_BASE_URL", ""),
        vlm_base_url=os.getenv("VLM_BASE_URL", ""),
        gemini_timeout_s=_env_int("GEMINI_TIMEOUT_S", 120),
        openai_timeout_s=_env_int("OPENAI_TIMEOUT_S", 90),
        cerebras_timeout_s=_env_int("CEREBRAS_TIMEOUT_S", 60),
        ollama_timeout_s=_env_int("OLLAMA_TIMEOUT_S", 300),
        vllm_timeout_s=_env_int("VLLM_TIMEOUT_S", 180),
        vlm_timeout_s=_env_int("VLM_TIMEOUT_S", 180),
        vllm_supports_large_context=_env_bool("VLLM_SUPPORTS_LARGE_CONTEXT", False),
        vlm_pdf_render_dpi=_env_int("VLM_PDF_RENDER_DPI", 144),
        vlm_pages_per_prompt=_env_int("VLM_PAGES_PER_PROMPT", 1),
        vlm_max_pages=_env_int("VLM_MAX_PAGES", 40),
        vlm_passes=_env_int("INVOICE_VLM_PASSES", 2),
        invoice_vlm_helper_model=os.getenv("INVOICE_VLM_HELPER_MODEL", ""),
        
        invoice_chunk_size_gemini=_env_int_any(("INVOICE_CHUNK_SIZE_GEMINI",), 100000),
        invoice_chunk_size_openai=_env_int_any(("INVOICE_CHUNK_SIZE_OPENAI",), 80000),
        invoice_chunk_size_ollama=_env_int_any(("INVOICE_CHUNK_SIZE_OLLAMA",), 20000),
        invoice_chunk_size_cerebras=_env_int_any(("INVOICE_CHUNK_SIZE_CEREBRAS", "CHUNK_SIZE_CEREBRAS"), 3500),
        invoice_chunk_size_vllm=_env_int_any(("INVOICE_CHUNK_SIZE_VLLM", "CHUNK_SIZE_VLLM"), 20000),
        invoice_vllm_max_workers=_env_int_any(("INVOICE_VLLM_MAX_WORKERS", "VLLM_MAX_WORKERS"), 2),
        invoice_chunk_overlap_default=_env_int("INVOICE_CHUNK_OVERLAP_DEFAULT", 600),
        invoice_chunk_overlap_vllm=_env_int("INVOICE_CHUNK_OVERLAP_VLLM", 0),
        chunk_size_default=_env_int("CHUNK_SIZE_DEFAULT", 100000),
        default_chunk_max_workers=_env_int("DEFAULT_CHUNK_MAX_WORKERS", 2),
        llm_max_char_buffer=_env_int("LLM_MAX_CHAR_BUFFER", 12000),
        web_job_max_workers=_env_int("WEB_JOB_MAX_WORKERS", 2),
        web_job_retention_s=_env_int("WEB_JOB_RETENTION_S", 3600),
        web_job_max_stored=_env_int("WEB_JOB_MAX_STORED", 100),
        currency_db_json=os.getenv("CURRENCY_DB_JSON", "[]"),
    )
