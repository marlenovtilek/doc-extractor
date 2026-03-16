from cerebras.cloud.sdk import Cerebras
import os
from dotenv import load_dotenv

# Загружаем настройки из .env
load_dotenv()

api_key = os.getenv("CEREBRAS_API_KEY")
if not api_key:
    print("Ошибка: CEREBRAS_API_KEY не найден в .env")
    exit(1)

client = Cerebras(api_key=api_key)

try:
    print("Запрашиваю список моделей...")
    models = client.models.list()
    
    print("\n--- Доступные модели ---")
    for model in models.data:
        print(f"ID: {model.id} | Name: {model.object}")
        
except Exception as e:
    print(f"\nОшибка при подключении к Cerebras: {e}")