import requests
import json
import time
import os

# ============================================
# НАСТРОЙКИ ТЕСТА
# ============================================
TEST_FILE = 'files_to_testing/217.txt'
MODEL = 'gemini::gemini-2.5-flash-lite'  # Варианты: 'gemini', 'cerebras', 'ollama::qwen3:14b'
URL = 'http://127.0.0.1:8000/web/extract/'
# ============================================

with open(TEST_FILE, 'r', encoding='utf-8') as f:
    ocr_text = f.read()

print(f"🚀 Отправка файла {TEST_FILE} ({len(ocr_text)} симв.) к модели {MODEL}...")
start_time = time.time()

try:
    response = requests.post(
        URL,
        json={'document_code': '04021', 'ocr_draft': ocr_text, 'model': MODEL},
        timeout=180
    )
    response.raise_for_status()  # Бросит ошибку, если статус не 2xx
    
    result = response.json()
    items = result.get('data', {}).get('items', [])
    elapsed = time.time() - start_time
    server_time = result.get('duration', 0)

    print(f"✅ Успешно! (Сервер: {server_time}s | Общее: {elapsed:.2f}s)")
    print(f"📦 Извлечено товаров: {len(items)}\n")

    # Вывод превью первых 5 товаров
    for i, item in enumerate(items[:5], 1):
        desc = str(item.get('description', ''))[:60].replace('\n', ' ')
        print(f"  {i}. {desc}...")
    if len(items) > 5:
        print(f"  ... и еще {len(items) - 5} позиций.")

    # Получаем исходное имя файла без пути и расширения (например: '217.txt' -> '217')
    base_name = os.path.splitext(os.path.basename(TEST_FILE))[0]
    
    # Формируем имя выходного файла в корне проекта
    out_file = f"{base_name}.json"
    
    # Сохранение полного JSON-ответа
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Полный ответ сохранён в корень проекта: {out_file}")

except requests.exceptions.RequestException as e:
    print(f"❌ Ошибка сети/API: {e}")
    if 'response' in locals() and hasattr(response, 'text') and response.text:
        print(f"Детали: {response.text[:500]}")
except Exception as e:
    print(f"❌ Системная ошибка: {e}")