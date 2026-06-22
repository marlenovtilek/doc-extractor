import json
import re
from typing import Tuple, List

def clean_invoice_text(raw_text: str) -> str:
    """Очистка OCR текста от лишнего шума"""
    if not raw_text:
        return ""
    text = str(raw_text).replace('\r', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = []
    for line in text.split('\n'):
        clean_line = re.sub(r'[ \t]+', ' ', line).strip()
        if clean_line:
            lines.append(clean_line)
    return '\n'.join(lines)


def extract_json_array(text: str) -> list:
    text = str(text).strip()
    
    # Убираем популярную ошибку: текст перед JSON
    text = re.sub(r'^[^{}\[\]]*', '', text)

    # Ищем массив или объект с полем items
    match_arr = re.search(r'\[.*\]', text, re.DOTALL)
    if match_arr:
        try:
            return json.loads(match_arr.group(0))
        except:
            pass

    match_obj = re.search(r'\{.*\}', text, re.DOTALL)
    if match_obj:
        try:
            data = json.loads(match_obj.group(0))
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            return [data]
        except:
            pass
            
    return []


def validate_and_format_invoice(llm_response: str) -> Tuple[bool, str, List[dict]]:
    """
    Валидирует ответ LLM.
    Возвращает: (is_valid, error_message, valid_items)
    is_valid = True означает, что чанк отработан (даже если там 0 товаров).
    """
    if not llm_response:
        # Пустой ответ — это не ошибка, просто в чанке ничего нет
        return True, "Empty response", []

    try:
        parsed_data = extract_json_array(llm_response)
    except ValueError as e:
        if len(llm_response) < 200:
            return True, "Text refusal (no items)", []
        return False, f"JSON Parse Error: {e}", []

    if not isinstance(parsed_data, list):
        parsed_data = [parsed_data]

    # Если массив пустой - всё ок, в этом чанке нет товаров (фоллбэк вызывать не надо!)
    if not parsed_data:
        return True, "", []

    valid_items = []
    for item in parsed_data:
        if not isinstance(item, dict):
            continue

        name = item.get('description')
        # Берем только те записи, где есть хоть какое-то описание
        if name and str(name).strip().lower() not in ['none', 'null', '']:
            
            # Очистка полей
            hs = item.get('hs_code')
            if str(hs).strip().lower() in ['none', 'null', '']:
                item['hs_code'] = None

            item['description'] = re.sub(r'\s+', ' ', str(name)).strip()

            if isinstance(item.get("currency_code"), str):
                cc = item["currency_code"].strip().upper()
                item["currency_code"] = cc if cc else None

            if isinstance(item.get("currency_name"), str):
                cn = item["currency_name"].strip()
                item["currency_name"] = cn if cn else None

            valid_items.append(item)

    # Успешно возвращаем отфильтрованные товары (даже если список стал пустым)
    return True, "", valid_items
