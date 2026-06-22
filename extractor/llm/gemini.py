import json
import urllib.request
import logging
from .base import LLMProvider

logger = logging.getLogger(__name__)

class GeminiProvider(LLMProvider):
    @property
    def supports_large_context(self) -> bool:
        return True

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str,
        timeout: int | None = None,
    ) -> str:
        # 1. Формируем чистый ID
        m_name = model_id.split("::")[-1] if "::" in model_id else model_id
        request_timeout = timeout or self.default_timeout_s
        
        # 2. Выбор версии API (v1beta нужна для 2.0 lite)
        version = "v1beta" if "preview" in m_name or "2.0" in m_name or "2.5" in m_name else "v1"
        url = f"https://generativelanguage.googleapis.com/{version}/models/{m_name}:generateContent?key={self.api_key}"
        
        payload = {
            "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}
        }
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            data = self._request_json(
                req,
                timeout=request_timeout,
                provider_name="Gemini",
                model_id=m_name,
            )
            return data['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            logger.error(f"Gemini API Error ({m_name} via {version}): {e}")
            raise
