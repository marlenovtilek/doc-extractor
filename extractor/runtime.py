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


@dataclass(frozen=True)
class RuntimeSettings:
    langextract_api_key: str
    llm_model_primary: str
    llm_model_fallback: str
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
    currency_db_json: str


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        langextract_api_key=os.getenv("LANGEXTRACT_API_KEY", ""),
        llm_model_primary=os.getenv("LLM_MODEL_PRIMARY", "cerebras"),
        llm_model_fallback=os.getenv("LLM_MODEL_FALLBACK", "gemini"),
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
        currency_db_json=os.getenv("CURRENCY_DB_JSON", "[]"),
    )


def clear_runtime_settings_cache() -> None:
    get_runtime_settings.cache_clear()
