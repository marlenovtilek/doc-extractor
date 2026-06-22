import json
import urllib.request
import logging
from .base import LLMProvider

logger = logging.getLogger(__name__)

class CerebrasProvider(LLMProvider):
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
        m_id = model_id.split("::")[-1] if "::" in model_id else model_id
        request_timeout = timeout or self.default_timeout_s
        
        payload = {
            "model": m_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"}
        }
        
        # У Cerebras эндпоинт v1/chat/completions
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                'Content-Type': 'application/json', 
                'Authorization': f'Bearer {self.api_key}'
            }
        )
        try:
            data = self._request_json(
                req,
                timeout=request_timeout,
                provider_name="Cerebras",
                model_id=m_id,
            )
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Cerebras Error: {e}")
            raise
