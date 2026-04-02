# extractor/documents/protocol.py
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any

from ..base import DocumentFieldSchema, DocumentSchema, DocumentHandler
from ...integrations.llm import get_llm_provider
from ...config.runtime import get_runtime_settings
from ...integrations.providers import build_model_spec, resolve_model_target
from ...observability.metrics import RunMetrics, timer

PROTOCOL_PROMPT = """
# ROLE
Ты — extractor данных из OCR протоколов испытаний (рус/eng, шумный OCR).
Верни ТОЛЬКО валидный JSON-объект (без markdown и комментариев) строго по схеме:
{
  "ComplianceDocDetails":[
    {
      "DocKindCode": {"Value": null, "CodeListId": "2021"},
      "DocName": null,
      "DocId": null,
      "DocCreationDate": null,
      "LaboratoryDetails": {
        "BusinessEntityId": {"Value": null, "CodeListId": "2021"},
        "BusinessEntityTypeName": null,
        "BusinessEntityName": null,
        "SubjectAddressDetails":[
          {
            "AddressKindCode": null,
            "UnifiedCountryCode": {"Value": null, "CodeListId": "2021"},
            "TerritoryCode": null,
            "RegionName": null,
            "DistrictName": null,
            "CityName": null,
            "SettlementName": null,
            "StreetName": null,
            "BuildingNumberId": null,
            "RoomNumberId": null,
            "PostCode": null,
            "PostOfficeBoxId": null
          }
        ],
        "AccreditationCertificateDetails":[
          {
            "DocKindName": null,
            "DocId": null,
            "DocStartDate": null,
            "EventDate": null,
            "DocValidityDate": null
          }
        ]
      }
    }
  ]
}

Правила:
1) Один OCR-документ = один объект в массиве ComplianceDocDetails.
2) Если поле не найдено -> null. Не выдумывай значения.
3) Не добавляй лишние поля. Ключи и вложенность строго как в схеме.
4) Даты только в формате YYYY-MM-DDThh:mm:ss. Если есть только дата -> T00:00:00.
5) Для формата DD.MM.YYYY трактуй как день.месяц.год (не US-формат).
6) Для диапазона дат:
   - DocCreationDate: дата протокола (обычно после "от").
   - DocStartDate: дата "от" аттестата.
   - DocValidityDate: дата "до"/"действителен до".
   - EventDate: только если явно указано "дата регистрации"/"зарегистрирован".
7) LaboratoryDetails заполняй по данным лаборатории из шапки (до/рядом с заголовком протокола), НЕ по "Заявитель", "Изготовитель", "Заказчик".
8) BusinessEntityId.Value и UnifiedCountryCode.Value — только двухбуквенный код страны (KG, KZ, RU, BY, AM, TJ, UZ, CN и т.п.) или null. Никаких индексов.
9) BusinessEntityTypeName — только форма организации (АО, ТОО, ООО, ГУ, ОсОО и т.п.) без полного названия.
10) BusinessEntityName — только имя организации, без таблиц.
11) SubjectAddressDetails:
   - AddressKindCode: код вида адреса (например 01/02), иначе null.
   - разнеси адрес по полям (CityName/SettlementName/StreetName/BuildingNumberId/PostCode).
12) AccreditationCertificateDetails: если данных нет, верни[].
13) Не копируй таблицы "РЕЗУЛЬТАТЫ ИСПЫТАНИЙ", нормы, методики в поля.
14) Убирай OCR-мусор (![](...), ##).
15) Не выводи ничего кроме JSON.
"""

# =====================================================================
# ВЕСЬ ТВОЙ КОД ИЗ УЗЛА 1772436931708 (БЕЗ ИЗМЕНЕНИЙ)
# =====================================================================

def _norm_space(text):
    if text is None: return ""
    return re.sub(r"\s+", " ", str(text)).strip()

def _normalize_ocr_text(text):
    if text is None: return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _is_effectively_empty_ocr(text):
    s = _normalize_ocr_text(text)
    if not s: return True
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", s)
    s = re.sub(r"^#+\s*", " ", s, flags=re.MULTILINE)
    s = _norm_space(s)
    if not s: return True
    core = re.sub(r"[^A-Za-zА-Яа-яЁё0-9]+", "", s)
    return len(core) < 8

def _strip(v):
    if v is None: return None
    s = _norm_space(v)
    if not s or s.lower() in {"null", "none", "unknown", "неизвестно", "n/a", "-"}: return None
    return s

def _up(v):
    v = _strip(v)
    return v.upper() if v else None

def _normalize_country_code(value):
    v = _strip(value)
    if not v: return None
    v = v.upper()
    cyr_to_lat = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","Х":"X","У":"Y"})
    v = v.translate(cyr_to_lat)
    m = re.match(r"^\s*([A-Z]{2})(?:\b|[./\- ]|$)", v)
    return m.group(1) if m else None

def _normalize_doc_kind_code(value, doc_id):
    v = _up(value)
    if not v: return None
    compact = re.sub(r"[^A-Z0-9]", "", v)
    doc_compact = re.sub(r"[^A-Z0-9]", "", _up(doc_id) or "")
    if doc_compact and compact:
        if compact == doc_compact or compact.endswith(doc_compact) or doc_compact.endswith(compact): return None
    if re.fullmatch(r"\d{1,12}", compact): return None
    if len(v) > 30 or " " in v: return None
    return v

def _normalize_address_kind_code(value):
    v = _up(value)
    if not v: return "01"
    if re.fullmatch(r"0\d", v): return v
    m = re.search(r"\b(0\d)\b", v)
    if m: return m.group(1)
    aliases = {"LEGAL_ADDRESS": "01", "REGISTRATION_ADDRESS": "01", "ACTUAL_ADDRESS": "02", "FACTUAL_ADDRESS": "02"}
    return aliases.get(v, "01")

def _normalize_business_entity_id(value, fallback_country_code):
    return _normalize_country_code(value) or _normalize_country_code(fallback_country_code)

def _infer_legal_form(value):
    s = _up(value)
    if not s: return None
    forms =["ГУ", "ТОО", "ООО", "ОАО", "ЗАО", "ИП", "АО", "ПАО", "ОСОО", "ЧП"]
    tokens =[t for t in re.split(r"[^A-ZА-ЯЁ0-9]+", s) if t]
    for token in tokens:
        if token in forms: return token
    return None

def _clean_business_entity_name(value):
    s = _strip(value)
    if not s: return None
    s = s.replace("« ", "«").replace(" »", "»")
    s = re.sub(r"\s*##+\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    stop_patterns =[r"\bюридический\s+адрес\b", r"\bадрес\s*[:\-]\b", r"\bконтактн\w*\s+данн\w*\b", r"\bтел\.?\b", r"\bтелефон\b", r"\bдата\s+поступления\b", r"(?:^|[\s\-])2\.\s*дата\b", r"\|\s*наименование\s+показателей\b", r"##\s*результаты\s+испытаний\b"]
    for pat in stop_patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m: s = s[: m.start()].strip(" -;,.")
    if len(s) > 300: s = s[:300].rstrip(" -;,.")
    return s or None

def _extract_organization_name(value):
    s = _clean_business_entity_name(value)
    if not s: return None
    entity_token = r"(ГУ|АО|ТОО|ООО|ОАО|ПАО|ЗАО|ОСОО|ОсОО|ИП|ЧП)"
    m = re.search(rf"\b{entity_token}\b[^#|\n]{{0,220}}?[»\"]", s, flags=re.IGNORECASE)
    if not m: m = re.search(rf"\b{entity_token}\b[^#|\n]{{0,220}}", s, flags=re.IGNORECASE)
    if m: s = m.group(0).strip(" -;,.")
    s = re.split(r"\b(?:адрес|юридический\s+адрес|тел\.?|телефон|контакт|протокол|дата|заказчик|исполнитель|отдел)\b", s, maxsplit=1, flags=re.IGNORECASE)[0].strip(" -;,.")
    s = re.sub(r"\s+", " ", s).strip()
    if not re.search(r"\b(ГУ|АО|ТОО|ООО|ОАО|ПАО|ЗАО|ОСОО|ОсОО|ИП|ЧП)\b", s, flags=re.IGNORECASE):
        if len(s) > 120: return None
    return s or None

def _is_noisy_entity_name(value):
    s = _strip(value)
    if not s: return True
    low = s.lower()
    bad_markers =["заявитель", "дата поступления", "наименование образца", "результаты испытаний", "частичная или полная перепечатка", "адрес:", "тел:"]
    if any(m in low for m in bad_markers): return True
    if "##" in s or "|" in s or len(s) > 260 or s.count(" - ") >= 2: return True
    return False

def _extract_header_block(ocr):
    if not ocr: return ""
    candidates = []
    for pat in[r"\bпротокол\s+испытан", r"\btest\s+report\b", r"\breport\b"]:
        m = re.search(pat, ocr, flags=re.IGNORECASE)
        if m: candidates.append(m.start())
    cut = min(candidates) if candidates else min(len(ocr), 1800)
    header = ocr[:cut]
    header = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", header)
    header = re.sub(r"^#+\s*", "", header, flags=re.MULTILINE)
    return _normalize_ocr_text(header)

def _extract_clean_lines(text):
    return[clean for line in str(text or "").splitlines() if (clean := _strip(re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)))]

def _ocr_to_digits(token):
    t = str(token or "").strip()
    trans = str.maketrans({"O":"0","О":"0","o":"0","I":"1","І":"1","Ӏ":"1","l":"1","|":"1","!":"1"})
    return re.sub(r"[^0-9]", "", t.translate(trans))

def _build_iso(y, mo, d):
    try:
        y_raw = str(y).strip()
        y, mo, d = int(y_raw), int(mo), int(d)
        if len(y_raw) <= 2: y += 2000
        elif y < 1900 or y > 2100: return None
        return datetime(y, mo, d, 0, 0, 0).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None

def _iso(value):
    value = _strip(value)
    if not value: return None
    s = str(value)
    s = re.sub(r"\b(?:год|г\.?|year)\b", " ", s, flags=re.IGNORECASE)
    s = s.replace("—", "-").replace("–", "-")
    s = _norm_space(s)
    s = re.sub(r"\s*([./-])\s*", r"\1", s)
    m = re.search(r"([0-9OОoIІӀl|! ]{1,4}[./-][0-9OОoIІӀl|! ]{1,4}[./-][0-9OОoIІӀl|! ]{2,4})", s)
    if m: s = m.group(0)
    m = re.fullmatch(r"([0-9OОoIІӀl|! ]{1,4})[./-]([0-9OОoIІӀl|! ]{1,4})[./-]([0-9OОoIІӀl|! ]{2,4})", s)
    if m:
        p1, p2, p3 = _ocr_to_digits(m.group(1)), _ocr_to_digits(m.group(2)), _ocr_to_digits(m.group(3))
        if len(p1) == 4:
            iso = _build_iso(p1, p2, p3)
            if iso: return iso
        iso = _build_iso(p3, p2, p1)
        if iso: return iso
    m = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s)
    if m: return _build_iso(m.group(1), m.group(2), m.group(3))
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if m: return _build_iso(m.group(3), m.group(2), m.group(1))
    m = re.fullmatch(r"(\d{1,2})[./-](\d{4})", s)
    if m:
        try: return datetime(int(m.group(2)), int(m.group(1)), 1, 0, 0, 0).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception: return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception: return None

def _as_list(v):
    if isinstance(v, list): return v
    if isinstance(v, dict): return [v]
    return []

def _empty_payload():
    return {
        "ComplianceDocDetails":[{
            "DocKindCode": {"Value": None, "CodeListId": "2021"},
            "DocName": None, "DocId": None, "DocCreationDate": None,
            "LaboratoryDetails": {
                "BusinessEntityId": {"Value": None, "CodeListId": "2021"},
                "BusinessEntityTypeName": None, "BusinessEntityName": None,
                "SubjectAddressDetails": [], "AccreditationCertificateDetails":[],
            }
        }]
    }

def _empty_address():
    return {
        "AddressKindCode": None, "UnifiedCountryCode": {"Value": None, "CodeListId": "2021"},
        "TerritoryCode": None, "RegionName": None, "DistrictName": None, "CityName": None,
        "SettlementName": None, "StreetName": None, "BuildingNumberId": None, "RoomNumberId": None,
        "PostCode": None, "PostOfficeBoxId": None,
    }

def _empty_cert():
    return {"DocKindName": None, "DocId": None, "DocStartDate": None, "EventDate": None, "DocValidityDate": None}

def _deep_merge(dst, src):
    if not isinstance(dst, dict) or not isinstance(src, dict): return dst
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict): _deep_merge(dst[k], v)
        else: dst[k] = v
    return dst

def _extract_json_from_llm(text):
    raw = str(text or "").strip()
    raw = re.sub(r"^```json", "```", raw, flags=re.IGNORECASE)
    if raw.startswith("```"):
        raw = re.sub(r"^```", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    candidate = m.group(0) if m else raw
    try:
        return json.loads(candidate)
    except Exception:
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        repaired = repaired.replace("None", "null").replace("True", "true").replace("False", "false")
        try: return json.loads(repaired)
        except Exception: return {}

def _normalize_doc_id(value):
    s = _strip(value)
    if not s: return None
    s = re.sub(r"^(?:№|N[OОЕE]?\.?)\s*", "", s, flags=re.IGNORECASE)
    s = re.split(r"\b(?:от|dated?)\b", s, maxsplit=1, flags=re.IGNORECASE)[0]
    s = re.sub(r"\s+", " ", s).strip()
    if re.fullmatch(r"(?:\d\s+){1,10}\d", s): s = re.sub(r"\s+", "", s)
    s = s.strip(" ,;:.")
    if len(s) > 50: return None
    if re.search(r"(гост|gost|iso|iec|есэгт)", s, flags=re.IGNORECASE): return None
    if not re.search(r"\d", s): return None
    if re.search(r"(ул\.?|улиц|адрес|тел|заказ)", s, flags=re.IGNORECASE): return None
    return s or None

def _is_protocol_doc_id(value):
    s = _normalize_doc_id(value)
    if not s: return False
    if len(s) > 20: return False
    letters = re.sub(r"[^A-Za-zА-Яа-я]", "", s)
    digits = re.sub(r"[^0-9]", "", s)
    if not digits: return False
    if len(letters) > 4 and len(digits) <= 2: return False
    if re.search(r"[A-Za-zА-Яа-я]{5,}\.", s): return False
    return True

def _extract_doc_header(ocr):
    doc_name = doc_id = doc_date = None
    ocr_date = r"[0-9OОoIІӀl|! ]{1,4}\s*[./-]\s*[0-9OОoIІӀl|! ]{1,4}\s*[./-]\s*[0-9OОoIІӀl|! ]{2,4}"
    if re.search(r"протокол\s+испытан", ocr, flags=re.IGNORECASE): doc_name = "ПРОТОКОЛ ИСПЫТАНИЙ"
    elif re.search(r"\btest\s+report\b", ocr, flags=re.IGNORECASE): doc_name = "TEST REPORT"
    anchor = re.search(r"(?:протокол\s+испытан[ийя]?|test\s+report)", ocr, flags=re.IGNORECASE)
    window = ocr[anchor.start() : anchor.start() + 450] if anchor else ocr[:700]
    patterns =[
        rf"(?:протокол\s+испытан[ийя]?|test\s+report)[^\n]{{0,160}}?(?:№|N[OОЕE]?\.?)\s*([A-Za-zА-Яа-я0-9.\-/ ]{{1,40}})(?:[^\n]{{0,120}}?\b(?:от|dated?)\b\s*({ocr_date}))?",
        rf"(?:№|N[OОЕE]?\.?)\s*([A-Za-zА-Яа-я0-9.\-/ ]{{1,40}})\s*(?:от|dated?)\s*({ocr_date})",
        r"(?:номер\s+протокола|номер\s+документа)\s*[:\-]?\s*([A-Za-zА-Яа-я0-9.\-/]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, window, flags=re.IGNORECASE)
        if not m: continue
        if not doc_id and m.group(1): doc_id = _normalize_doc_id(m.group(1))
        if len(m.groups()) >= 2 and m.group(2) and not doc_date: doc_date = _iso(m.group(2))
        if doc_id and doc_date: break
    if not doc_date:
        m = re.search(rf"\b(?:от|dated?)\b\s*({ocr_date})", window, flags=re.IGNORECASE)
        if m: doc_date = _iso(m.group(1))
    if not doc_date:
        m = re.search(ocr_date, window, flags=re.IGNORECASE)
        if m: doc_date = _iso(m.group(0))
    if not doc_id:
        m = re.search(r"(?:№|N[OОЕE]?\.?)\s*([A-Za-zА-Яа-я0-9.\-/ ]{2,30})", window, flags=re.IGNORECASE)
        if m: doc_id = _normalize_doc_id(m.group(1))
    return doc_name, doc_id, doc_date

def _extract_laboratory_entity(ocr):
    header = _extract_header_block(ocr)
    lines = _extract_clean_lines(header)
    if not lines: return None, None
    best_line, best_score = None, -10**9
    for line in lines:
        low = line.lower()
        score = 0
        if re.search(r"\b(гу|ао|тоо|ооо|осоо|ип|пао|оао|зао|чп)\b", line, flags=re.IGNORECASE): score += 4
        for kw in["филиал", "центр", "лаборатор", "институт", "диагност", "экспертиз", "служб"]:
            if kw in low: score += 2
        if re.search(r"\b\d{5,6}\b", line): score -= 2
        if re.search(r"(юридический\s+адрес|адрес|тел\.?|телефон|phone|стр\.)", low): score -= 3
        if "##" in line: score -= 2
        if re.search(r"(наименование\s+показателей|нормы\s+нд|фактическ\w+\s+показател)", low): score -= 6
        if len(line) > 220: score -= 2
        if score > best_score:
            best_score = score
            best_line = line
    entity_name = _clean_business_entity_name(best_line)
    if entity_name:
        entity_name = _extract_organization_name(entity_name) or entity_name
        entity_name = re.split(r"\bаттестат\s+аккредитац", entity_name, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;:-")
        shortened = re.split(r"\bиспытательн[а-яё\s-]*лаборатор[а-яё\s-]*", entity_name, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;:-")
        if len(shortened) >= 8: entity_name = shortened
        entity_name = _extract_organization_name(entity_name) or _clean_business_entity_name(entity_name)
    entity_type = _infer_legal_form(entity_name)
    return entity_type, entity_name

def _extract_accreditation(ocr):
    cert = _empty_cert()
    cert["DocKindName"] = "Аттестат аккредитации"
    def _norm_id(raw):
        s = _strip(raw)
        if not s: return None
        cyr_to_lat = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","Х":"X","У":"Y"})
        s = s.upper().translate(cyr_to_lat)
        s = re.sub(r"\s*\.\s*", ".", s)
        s = re.sub(r"\s*-\s*", "-", s)
        return re.sub(r"\s+", " ", s).strip()

    header = _extract_header_block(ocr)
    m_event = re.search(r"(?:дата\s+регистрац\w*|зарегистрирован[ао]?)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", ocr, flags=re.IGNORECASE)
    if m_event: cert["EventDate"] = _iso(m_event.group(1))
    if re.search(r"сертификат\s+аккредитац", header, flags=re.IGNORECASE): cert["DocKindName"] = "Сертификат аккредитации"
    patterns =[
        r"(?:аттестат|сертификат)\s+аккредитац[а-я]*\s*(?:№|N[OО]?\.?)\s*([A-Za-zА-Яа-я0-9.\-\/ ]{3,50})\s*(?:от|dated?)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}).{0,120}?(?:до|по|valid\s+to|действителен\s+до)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"(?:аттестат|сертификат)\s+аккредитац[а-я]*\s*(?:№|N[OО]?\.?)\s*([A-Za-zА-Яа-я0-9.\-\/ ]{3,50})",
    ]
    for pat in patterns:
        m = re.search(pat, header, flags=re.IGNORECASE)
        if not m: continue
        if m.group(1): cert["DocId"] = _norm_id(m.group(1))
        if len(m.groups()) >= 2 and m.group(2): cert["DocStartDate"] = _iso(m.group(2))
        if len(m.groups()) >= 3 and m.group(3): cert["DocValidityDate"] = _iso(m.group(3))
        if cert.get("DocId") and (cert.get("DocStartDate") or cert.get("DocValidityDate")): break

    if not cert.get("DocStartDate") or not cert.get("DocValidityDate"):
        m_dates = re.search(r"от\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:г\.?)?\s*(?:до|по|действителен\s+до)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", header, flags=re.IGNORECASE)
        if m_dates:
            cert["DocStartDate"], cert["DocValidityDate"] = _iso(m_dates.group(1)), _iso(m_dates.group(2))
    if not cert.get("DocValidityDate"):
        m_valid = re.search(r"(?:действителен\s+до|действует\s+до)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", header, flags=re.IGNORECASE)
        if m_valid: cert["DocValidityDate"] = _iso(m_valid.group(1))
    if not cert.get("DocId"):
        m_id = re.search(r"\b([A-Za-zА-Яа-я]{1,3}\s*[.]\s*[A-Za-zА-Яа-я]\s*[.]?\s*\d{2}\s*[.]\s*\d{4})\b", header, flags=re.IGNORECASE)
        if m_id: cert["DocId"] = _norm_id(m_id.group(1))
    if cert.get("DocStartDate") and cert.get("DocValidityDate") and not cert.get("EventDate"):
        cert["EventDate"] = None
    return cert

def _split_address_fields(raw_address):
    address = _empty_address()
    s = _strip(raw_address)
    if not s: return address
    s = re.sub(r"^(?:юридический|фактический|почтовый)?\s*адрес\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    s = re.split(r"\b(?:тел\.?|телефон|phone|факс)\b", s, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;")
    m = re.search(r"\b(\d{5,6})\b", s)
    if m: address["PostCode"] = m.group(1)
    m = re.search(r"([A-Za-zА-Яа-яЁё\- ]{2,80}\s(?:область|обл\.|край|region))", s, flags=re.IGNORECASE)
    if m: address["RegionName"] = _strip(m.group(1).rstrip(","))
    m = re.search(r"([A-Za-zА-Яа-яЁё0-9\- ]+\s+район(?:ы)?)", s, flags=re.IGNORECASE)
    if m: address["DistrictName"] = _strip(m.group(1).rstrip(","))
    m = re.search(r"(?:г\.|город)\s*([A-Za-zА-Яа-яЁё\- ]{2,80})", s)
    if m: address["CityName"] = _strip(m.group(1).rstrip(","))
    m = re.search(r"\b(микрорайон|мкр\.?)\s*([A-Za-zА-Яа-яЁё0-9\- ]{1,40})", s, flags=re.IGNORECASE)
    if m: address["SettlementName"] = _strip(f"микрорайон {m.group(2).rstrip(',')}")
    else:
        m = re.search(r"\b(пос\.?|поселок|село|с\.)\s*([A-Za-zА-Яа-яЁё0-9\- ]{1,60})", s, flags=re.IGNORECASE)
        if m: address["SettlementName"] = _strip(m.group(2).rstrip(","))
    m = re.search(r"(?:ул\.|улица|пр\.|проспект|пер\.|переулок|бульвар|шоссе|тракт|road|street|st\.)\s*([A-Za-zА-Яа-яЁё0-9\- ]{1,80})", s, flags=re.IGNORECASE)
    if m: address["StreetName"] = _strip(m.group(1).rstrip(","))
    m = re.search(r"(?:дом|д\.|building|bldg\.?|зд\.)\s*([A-Za-zА-Яа-я0-9\-/]{1,30})", s, flags=re.IGNORECASE)
    if m: address["BuildingNumberId"] = _strip(m.group(1).rstrip(","))
    elif address["StreetName"]:
        m = re.search(r",\s*([A-Za-zА-Яа-я0-9\-/]{1,10})\s*$", s)
        if m: address["BuildingNumberId"] = _strip(m.group(1))
    m = re.search(r"(?:кв\.|оф\.|пом\.|каб\.|room|suite)\s*([A-Za-zА-Яа-я0-9\-/]{1,20})", s, flags=re.IGNORECASE)
    if m: address["RoomNumberId"] = _strip(m.group(1).rstrip(","))
    if not address["CityName"]:
        city_aliases = {"алматы": "Алматы", "астана": "Астана", "шымкент": "Шымкент", "бишкек": "Бишкек", "москва": "Москва", "минск": "Минск", "душанбе": "Душанбе", "ташкент": "Ташкент", "ереван": "Ереван"}
        low = s.lower()
        for k, v in city_aliases.items():
            if re.search(rf"\b{k}\b", low):
                address["CityName"] = v; break
    return address

def _extract_lab_address_candidates(ocr):
    header = _extract_header_block(ocr)
    lines = _extract_clean_lines(header)
    scored =[]
    for i, line in enumerate(lines):
        low = line.lower()
        score = 0
        if re.search(r"\b\d{5,6}\b", line): score += 3
        if re.search(r"(?:г\.|город|область|район|улица|ул\.|дом|д\.|микрорайон|мкр\.?|проспект|пр\.|кв\.|оф\.|road|street)", low): score += 3
        if "адрес" in low: score += 2
        if re.search(r"(тел\.?|телефон|phone|факс|стр\.)", low): score -= 2
        if re.search(r"(аттестат|аккредитац)", low): score -= 2
        if len(line) > 220: score -= 1
        if score >= 2: scored.append((score, i, line))
    ranked =[x[2] for x in sorted(scored, key=lambda t: (-t[0], t[1]))]
    unique, seen =[], set()
    for item in ranked:
        if item.lower() not in seen:
            seen.add(item.lower())
            unique.append(item)
    return unique[:3]

def _country_from_city(city_name):
    city = _up(city_name)
    if not city: return None
    mapping = {"АЛМАТЫ": "KZ", "АСТАНА": "KZ", "ШЫМКЕНТ": "KZ", "БИШКЕК": "KG", "МОСКВА": "RU", "МИНСК": "BY", "ТАШКЕНТ": "UZ", "ДУШАНБЕ": "TJ", "ЕРЕВАН": "AM"}
    for k, v in mapping.items():
        if k in city: return v
    return None

def _extract_country_code(text):
    low = str(text or "").lower()
    mapping = {"республика казахстан": "KZ", "казахстан": "KZ", "kazakhstan": "KZ", "кыргызская республика": "KG", "кыргызстан": "KG", "kyrgyz republic": "KG", "kyrgyzstan": "KG", "россия": "RU", "российская федерация": "RU", "russia": "RU", "беларусь": "BY", "belarus": "BY", "китай": "CN", "китайская народная республика": "CN", "china": "CN", "узбекистан": "UZ", "таджикистан": "TJ", "армения": "AM"}
    for k, v in mapping.items():
        if k in low: return v
    return None

def normalize_protocol_payload(payload: dict, ocr: str) -> dict:
    if not isinstance(payload, dict): payload = {}
    root = _empty_payload()
    _deep_merge(root, payload)
    docs = _as_list(root.get("ComplianceDocDetails"))
    if not docs: docs = [{}]
    else: docs = docs[:1]

    header_block = _extract_header_block(ocr)
    doc_name_fb, doc_id_fb, doc_date_fb = _extract_doc_header(ocr)
    be_type_fb, be_name_fb = _extract_laboratory_entity(ocr)
    cert_fb = _extract_accreditation(ocr)
    address_candidates = _extract_lab_address_candidates(ocr)
    parsed_address_candidates =[_split_address_fields(x) for x in address_candidates]
    country_code_fb = _extract_country_code(header_block) or _extract_country_code(" ".join(address_candidates)) or _extract_country_code(ocr[:2500])

    normalized_docs =[]
    for raw_doc in docs:
        doc = _empty_payload()["ComplianceDocDetails"][0]
        if isinstance(raw_doc, dict): _deep_merge(doc, raw_doc)

        doc["DocName"] = doc_name_fb or _strip(doc.get("DocName"))
        llm_doc_id = _normalize_doc_id(doc.get("DocId"))
        doc["DocId"] = doc_id_fb if _is_protocol_doc_id(doc_id_fb) else llm_doc_id
        doc["DocCreationDate"] = doc_date_fb or _iso(doc.get("DocCreationDate"))

        if not isinstance(doc.get("DocKindCode"), dict): doc["DocKindCode"] = {"Value": None, "CodeListId": "2021"}
        doc["DocKindCode"]["CodeListId"] = "2021"
        doc["DocKindCode"]["Value"] = _normalize_doc_kind_code(doc["DocKindCode"].get("Value"), doc["DocId"])

        lab = doc.get("LaboratoryDetails") if isinstance(doc.get("LaboratoryDetails"), dict) else {}
        doc["LaboratoryDetails"] = lab

        llm_lab_name = _extract_organization_name(lab.get("BusinessEntityName"))
        if _is_noisy_entity_name(llm_lab_name): llm_lab_name = None
        header_lab_name = _extract_organization_name(be_name_fb)
        if header_lab_name and not _infer_legal_form(header_lab_name): header_lab_name = None
        lab_name = header_lab_name or llm_lab_name
        lab["BusinessEntityName"] = lab_name

        type_from_name = _infer_legal_form(lab_name)
        type_from_field = _infer_legal_form(lab.get("BusinessEntityTypeName"))
        lab["BusinessEntityTypeName"] = type_from_name or type_from_field or be_type_fb

        if not isinstance(lab.get("BusinessEntityId"), dict): lab["BusinessEntityId"] = {"Value": None, "CodeListId": "2021"}
        lab["BusinessEntityId"]["CodeListId"] = "2021"
        lab["BusinessEntityId"]["Value"] = _normalize_business_entity_id(lab["BusinessEntityId"].get("Value"), country_code_fb)

        addresses = _as_list(lab.get("SubjectAddressDetails"))
        if not addresses and parsed_address_candidates: addresses = parsed_address_candidates
        address_fb = parsed_address_candidates[0] if parsed_address_candidates else _empty_address()

        norm_addresses =[]
        for raw_addr in addresses:
            addr = _empty_address()
            if isinstance(raw_addr, dict): _deep_merge(addr, raw_addr)
            if not isinstance(addr.get("UnifiedCountryCode"), dict): addr["UnifiedCountryCode"] = {"Value": None, "CodeListId": "2021"}
            addr["UnifiedCountryCode"]["CodeListId"] = "2021"
            addr["AddressKindCode"] = _normalize_address_kind_code(addr.get("AddressKindCode"))
            addr["TerritoryCode"] = _up(addr.get("TerritoryCode"))

            for field in["RegionName", "DistrictName", "CityName", "SettlementName", "StreetName", "BuildingNumberId", "RoomNumberId", "PostCode", "PostOfficeBoxId"]:
                addr[field] = _strip(addr.get(field)) or address_fb.get(field)

            if addr["CityName"] and re.fullmatch(r"(до|от|по|из|на|to|from)", addr["CityName"], flags=re.IGNORECASE): addr["CityName"] = address_fb.get("CityName")
            if addr["SettlementName"] and re.fullmatch(r"\d{1,4}", addr["SettlementName"]):
                if address_fb.get("SettlementName") and re.search(r"(микрорайон|мкр\.?|пос\.?|поселок|село|с\.)", address_fb.get("SettlementName") or "", flags=re.IGNORECASE):
                    addr["SettlementName"] = address_fb.get("SettlementName")

            addr["UnifiedCountryCode"]["Value"] = _normalize_country_code(addr["UnifiedCountryCode"].get("Value")) or _country_from_city(addr["CityName"]) or country_code_fb

            if addr["DistrictName"] and re.search(r"(микрорайон|мкр\.?)", addr["DistrictName"], flags=re.IGNORECASE):
                if not addr["SettlementName"]: addr["SettlementName"] = addr["DistrictName"]
                addr["DistrictName"] = None

            if addr["StreetName"] and re.fullmatch(r"[A-Za-zА-Яа-я0-9\-/]{1,20}", addr["StreetName"]):
                if not addr["BuildingNumberId"]:
                    addr["BuildingNumberId"] = addr["StreetName"]
                    addr["StreetName"] = None

            norm_addresses.append(addr)

        lab["SubjectAddressDetails"] = norm_addresses
        if not lab["BusinessEntityId"]["Value"]:
            for addr in norm_addresses:
                if isinstance(addr.get("UnifiedCountryCode"), dict) and _normalize_country_code(addr["UnifiedCountryCode"].get("Value")):
                    lab["BusinessEntityId"]["Value"] = _normalize_country_code(addr["UnifiedCountryCode"].get("Value"))
                    break

        certs = _as_list(lab.get("AccreditationCertificateDetails"))
        has_cert_data = any(cert_fb.get(k) for k in["DocId", "DocStartDate", "EventDate", "DocValidityDate"])
        if not certs: certs = [cert_fb] if has_cert_data else[]

        norm_certs =[]
        for raw_cert in certs:
            cert = _empty_cert()
            if isinstance(raw_cert, dict): _deep_merge(cert, raw_cert)
            cert["DocKindName"] = _strip(cert.get("DocKindName")) or cert_fb.get("DocKindName")
            cert["DocId"] = cert_fb.get("DocId") or _strip(cert.get("DocId"))
            cert["DocStartDate"] = cert_fb.get("DocStartDate") or _iso(cert.get("DocStartDate"))
            cert["DocValidityDate"] = cert_fb.get("DocValidityDate") or _iso(cert.get("DocValidityDate"))
            cert["EventDate"] = cert_fb.get("EventDate") or _iso(cert.get("EventDate"))
            if cert_fb.get("DocStartDate") and cert_fb.get("DocValidityDate") and not cert_fb.get("EventDate"): cert["EventDate"] = None
            norm_certs.append(cert)

        lab["AccreditationCertificateDetails"] = norm_certs
        normalized_docs.append(doc)

    return {"ComplianceDocDetails": normalized_docs}


# =====================================================================
# ХЭНДЛЕР
# =====================================================================

class ProtocolHandler(DocumentHandler):
    document_code = "22222"
    label = "Protocol testing"
    
    # Этот документ возвращает сложную структуру, поэтому используем тип object 
    # и просто вернем весь JSON внутри data["items"]
    schema = DocumentSchema(
        result_type="object",
        fields=(),
        item_fields=(),
    )

    def extract(self, *, ocr_draft: str, model: str | None = None) -> dict[str, Any]:
        metrics = RunMetrics()
        t_wall_start = time.perf_counter()
        
        target_model = resolve_model_target(model)
        fallback_target = resolve_model_target(get_runtime_settings().llm_model_fallback)
        
        with timer() as t_clean:
            ocr_normalized = _normalize_ocr_text(ocr_draft)
        metrics.t_clean_s = t_clean[0]

        if _is_effectively_empty_ocr(ocr_normalized):
            metrics.t_total_s = time.perf_counter() - t_wall_start
            return {
                "error": "Empty OCR text",
                "metrics": metrics.to_dict(),
                "model_id": build_model_spec(target_model.provider, target_model.model_id),
            }

        final_target = target_model
        fallback_used = False
        with timer() as t_llm:
            try:
                provider = get_llm_provider(target_model.provider)
                llm_text = provider.generate(
                    PROTOCOL_PROMPT,
                    f"TEXT TO PROCESS:\n{ocr_normalized}",
                    target_model.model_id,
                )
            except Exception:
                if fallback_target != target_model:
                    try:
                        fallback_provider = get_llm_provider(fallback_target.provider)
                        llm_text = fallback_provider.generate(
                            PROTOCOL_PROMPT,
                            f"TEXT TO PROCESS:\n{ocr_normalized}",
                            fallback_target.model_id,
                        )
                        final_target = fallback_target
                        fallback_used = True
                    except Exception:
                        llm_text = "{}"
                else:
                    llm_text = "{}"
        
        metrics.t_primary_llm_s = t_llm[0]

        with timer() as t_validate:
            # Парсим сырой ответ от LLM
            llm_payload = _extract_json_from_llm(llm_text)
            # Пропускаем через твой огромный скрипт нормализации (22222)
            normalized = normalize_protocol_payload(llm_payload, ocr_normalized)

        items = normalized.get("ComplianceDocDetails", [])
        
        metrics.t_validate_s = t_validate[0]
        metrics.primary_valid = bool(llm_payload)
        metrics.items_extracted = len(items)
        metrics.t_total_s = round(time.perf_counter() - t_wall_start, 3)

        metrics_payload = metrics.to_dict()
        metrics_payload["execution"] = {
            "primary_model": build_model_spec(target_model.provider, target_model.model_id),
            "fallback_model": (
                build_model_spec(fallback_target.provider, fallback_target.model_id)
                if fallback_target != target_model
                else None
            ),
            "final_model": build_model_spec(final_target.provider, final_target.model_id),
            "final_provider": final_target.provider,
            "fallback_used": fallback_used,
        }

        return {
            "metrics": metrics_payload,
            "model_id": build_model_spec(final_target.provider, final_target.model_id),
            "result_type": "object",
            "data": {
                "fields": {},
                # Возвращаем весь результат одним объектом в списке
                "items": items,
                "count": len(items),
            },
        }
