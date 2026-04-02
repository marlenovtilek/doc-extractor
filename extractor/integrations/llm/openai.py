import json
import urllib.request
import logging
from .base import LLMProvider

logger = logging.getLogger(__name__)

class OpenAIProvider(LLMProvider):
    @property
    def supports_large_context(self) -> bool:
        return True  # GPT-4o и gpt-4o-mini отлично справляются с длинными документами

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        # Убираем префикс если он есть
        m_id = model_id.split("::")[-1] if "::" in model_id else model_id
        request_timeout = timeout or self.default_timeout_s
        
        payload = {
            "model": m_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": { "type": "json_object" }, # 🔥 Включаем нативный JSON-мод
            "temperature": 0
        }
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            },
            method="POST"
        )
        
        try:
            data = self._request_json(
                req,
                timeout=request_timeout,
                provider_name="OpenAI",
                model_id=m_id,
            )
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            raise
