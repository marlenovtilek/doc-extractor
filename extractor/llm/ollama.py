import json
import urllib.request
import logging
from .base import LLMProvider

logger = logging.getLogger(__name__)

class OllamaProvider(LLMProvider):
    @property
    def supports_large_context(self) -> bool:
        # Для локальных моделей лучше оставить чанкинг (False), 
        # так как большие контексты сильно нагружают видеокарту на сервере.
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
        
        # Комбинируем промпт для классического API Ollama /generate
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        payload = {
            "model": m_id,
            "prompt": full_prompt,
            "stream": False,
            "format": "json", # 🔥 Гарантируем JSON на выходе
            "options": {
                "temperature": 0,
                "num_ctx": 32768,  # Увеличиваем контекст для тяжелых документов
                "num_predict": 4096 # Лимит на длину JSON
            },
            "keep_alive": "5m" # Держим модель в памяти 5 минут
        }
        
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
            method="POST"
        )
        
        try:
            data = self._request_json(
                req,
                timeout=request_timeout,
                provider_name="Ollama",
                model_id=m_id,
            )
            return data.get("response", "")
        except Exception as e:
            logger.error(f"Ollama Error (SSH Tunnel): {e}")
            raise
