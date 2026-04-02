from abc import ABC, abstractmethod
import json
import time
import urllib.error
import urllib.request


class LLMRateLimitError(RuntimeError):
    """Raised when an upstream provider responds with a rate-limit error."""


class LLMProviderError(RuntimeError):
    """Raised when an upstream provider request fails."""

class LLMProvider(ABC):
    def __init__(self, api_key: str = None, base_url: str = None, default_timeout_s: int = 90):
        self.api_key = api_key
        self.base_url = base_url
        self.default_timeout_s = default_timeout_s

    @property
    @abstractmethod
    def supports_large_context(self) -> bool:
        """Возвращает True, если модель может принять весь инвойс без чанкинга."""
        pass

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        """Метод для отправки запроса к API."""
        pass

    def _request_json(
        self,
        request: urllib.request.Request,
        *,
        timeout: int,
        provider_name: str,
        model_id: str,
        max_attempts: int = 3,
    ) -> dict:
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                status = getattr(exc, "code", None)
                body = exc.read().decode("utf-8", errors="ignore")
                retry_after = exc.headers.get("Retry-After") if exc.headers else None

                if status == 429:
                    if attempt < max_attempts:
                        delay_s = int(retry_after) if retry_after and retry_after.isdigit() else attempt * 2
                        time.sleep(delay_s)
                        last_error = exc
                        continue
                    raise LLMRateLimitError(
                        f"{provider_name} rate limit reached for model '{model_id}'. "
                        f"Try again a bit later or switch to another provider/model."
                    ) from exc

                if status in {408, 409, 425, 500, 502, 503, 504} and attempt < max_attempts:
                    time.sleep(attempt * 2)
                    last_error = exc
                    continue

                detail = body[:200].strip()
                raise LLMProviderError(
                    f"{provider_name} request failed for model '{model_id}'"
                    + (f": {detail}" if detail else ".")
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < max_attempts:
                    time.sleep(attempt * 2)
                    last_error = exc
                    continue
                raise LLMProviderError(
                    f"{provider_name} network error for model '{model_id}': {exc}"
                ) from exc

        raise LLMProviderError(
            f"{provider_name} request failed for model '{model_id}': {last_error}"
        )
