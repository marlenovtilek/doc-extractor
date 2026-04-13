import json
import logging
import urllib.request
from typing import Iterable

from .base import LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


def _build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


class VLMProvider(LLMProvider):
    @property
    def supports_large_context(self) -> bool:
        return False

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        raise LLMProviderError(
            "VLM provider requires visual inputs and is not available in text-only extraction flows."
        )

    def generate_from_images(
        self,
        system_prompt: str,
        user_prompt: str,
        image_urls: Iterable[str],
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        m_id = model_id.split("::", 1)[-1] if "::" in model_id else model_id
        request_timeout = timeout or self.default_timeout_s
        content: list[dict[str, object]] = [{"type": "text", "text": user_prompt}]
        for image_url in image_urls:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
            )

        payload = {
            "model": m_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
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
                provider_name="VLM",
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
            logger.error(f"VLM Error: {exc}")
            raise
