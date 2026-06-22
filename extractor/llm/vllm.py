import json
import logging
import urllib.request

from .base import LLMProvider

logger = logging.getLogger(__name__)


def _build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


class VLLMProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_timeout_s: int = 180,
        supports_large_context: bool = False,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, default_timeout_s=default_timeout_s)
        self._supports_large_context = supports_large_context

    @property
    def supports_large_context(self) -> bool:
        return self._supports_large_context

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        m_id = model_id.split("::", 1)[-1] if "::" in model_id else model_id
        request_timeout = timeout or self.default_timeout_s

        payload = {
            "model": m_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            _build_chat_completions_url(self.base_url or ""),
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )

        try:
            data = self._request_json(
                req,
                timeout=request_timeout,
                provider_name="vLLM",
                model_id=m_id,
            )
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                return "".join(parts)
            return str(content)
        except Exception as exc:
            logger.error(f"vLLM Error: {exc}")
            raise
