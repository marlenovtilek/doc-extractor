import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv(override=False)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    doc_extractor_api_token: str
    langextract_api_key: str
    llm_model_primary: str
    llm_model_fallback: str
    model_auto_route: bool
    model_auto_route_small_doc: str
    model_auto_route_large_table: str
    model_auto_route_object_default: str
    auto_route_char_threshold: int
    auto_route_pipe_row_threshold: int
    openai_api_key: str
    openai_base_url: str
    openai_organization: str
    openai_model_default: str
    ollama_base_url: str
    ollama_api_key: str
    ollama_model_default: str
    ollama_timeout_s: int
    cerebras_base_url: str
    cerebras_api_key: str
    llm_max_workers_cerebras: int
    llm_max_char_buffer_cerebras: int
    cerebras_max_retries: int
    cerebras_retry_base_delay_s: float
    llm_max_char_buffer: int
    llm_max_workers_gemini: int
    llm_max_workers_openai: int
    extraction_timeout_s: float
    web_job_max_workers: int
    web_job_retention_s: int
    web_job_max_stored: int
    currency_db_json: str


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        doc_extractor_api_token=os.getenv("DOC_EXTRACTOR_API_TOKEN", ""),
        langextract_api_key=os.getenv("LANGEXTRACT_API_KEY", ""),
        llm_model_primary=os.getenv("LLM_MODEL_PRIMARY", "cerebras::llama3.1-8b"),
        llm_model_fallback=os.getenv("LLM_MODEL_FALLBACK", "gemini"),
        model_auto_route=_env_bool("MODEL_AUTO_ROUTE", True),
        model_auto_route_small_doc=os.getenv("MODEL_AUTO_ROUTE_SMALL_DOC", "gemini-flash"),
        model_auto_route_large_table=os.getenv("MODEL_AUTO_ROUTE_LARGE_TABLE", "cerebras"),
        model_auto_route_object_default=os.getenv(
            "MODEL_AUTO_ROUTE_OBJECT_DEFAULT", "gemini-flash"
        ),
        auto_route_char_threshold=_env_int("AUTO_ROUTE_CHAR_THRESHOLD", 12000),
        auto_route_pipe_row_threshold=_env_int("AUTO_ROUTE_PIPE_ROW_THRESHOLD", 25),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", ""),
        openai_organization=os.getenv("OPENAI_ORGANIZATION", ""),
        openai_model_default=os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
        ollama_model_default=os.getenv("OLLAMA_MODEL_DEFAULT", "qwen2.5:7b"),
        ollama_timeout_s=_env_int("OLLAMA_TIMEOUT_S", 120),
        cerebras_base_url=os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai"),
        cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
        llm_max_workers_cerebras=_env_int("LLM_MAX_WORKERS_CEREBRAS", 1),
        llm_max_char_buffer_cerebras=_env_int("LLM_MAX_CHAR_BUFFER_CEREBRAS", 100000),
        cerebras_max_retries=_env_int("CEREBRAS_MAX_RETRIES", 3),
        cerebras_retry_base_delay_s=_env_float("CEREBRAS_RETRY_BASE_DELAY_S", 2.0),
        llm_max_char_buffer=_env_int("LLM_MAX_CHAR_BUFFER", 5000),
        llm_max_workers_gemini=_env_int("LLM_MAX_WORKERS_GEMINI", 5),
        llm_max_workers_openai=_env_int("LLM_MAX_WORKERS_OPENAI", 5),
        extraction_timeout_s=_env_float("EXTRACTION_TIMEOUT_S", 180.0),
        web_job_max_workers=_env_int("WEB_JOB_MAX_WORKERS", 2),
        web_job_retention_s=_env_int("WEB_JOB_RETENTION_S", 3600),
        web_job_max_stored=_env_int("WEB_JOB_MAX_STORED", 200),
        currency_db_json=os.getenv("CURRENCY_DB_JSON", "[]"),
    )


def clear_runtime_settings_cache() -> None:
    get_runtime_settings.cache_clear()
