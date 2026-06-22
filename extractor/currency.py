"""
Currency utilities — mirrors the resolve_currency logic from the original
'Checking and sending request' code node (Node 1765342175106).
"""

import json
import re

from extractor.runtime import get_runtime_settings


def load_currency_db() -> list[dict]:
    """Load currency database from shared runtime settings."""
    raw = get_runtime_settings().currency_db_json
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def resolve_currency(raw: str | None, db: list[dict]) -> tuple[str | None, str | None]:
    """
    Return (currency_code, currency_name) by looking up *raw* in the DB.
    Matches first by code, then by name substring — same logic as original workflow.
    """
    if not raw or not db:
        return None, None

    key = str(raw).strip().upper()

    for row in db:
        if str(row.get("code", "")).upper() == key:
            return row["code"], row.get("name")

    for row in db:
        if key in str(row.get("name", "")).upper():
            return row["code"], row.get("name")

    return raw, None


def infer_currency_from_text(text: str | None, db: list[dict]) -> tuple[str | None, str | None]:
    """Infer currency from OCR text when the LLM omitted it in structured rows."""
    if not text:
        return None, None

    raw = str(text)
    upper = raw.upper()
    lower = re.sub(r"\s+", " ", raw.lower())

    for code, name in _COMMON_CURRENCY_NAMES.items():
        if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            return code, name

    for symbol, code in _CURRENCY_SYMBOL_TO_CODE.items():
        if symbol in raw:
            return code, _COMMON_CURRENCY_NAMES.get(code)

    for name, code in _CURRENCY_TEXT_TO_CODE.items():
        if name in lower:
            return code, _COMMON_CURRENCY_NAMES.get(code, name.title())

    for row in db:
        code = str(row.get("code", "")).strip().upper()
        name = str(row.get("name", "")).strip()
        if code and re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            return code, name or _COMMON_CURRENCY_NAMES.get(code)
        if name and name.lower() in lower:
            return code or None, name

    return None, None


def build_currency_db_string(db: list[dict]) -> str:
    """
    Serialise the currency DB to the plain-text block expected by the LLM prompt
    (mirrors the =CURRENCY DATABASE= section prepended in Node 1765260281035).
    """
    return json.dumps(db, ensure_ascii=False, indent=2)


_ISO_TO_RUSSIAN: dict[str, str] = {
    "AF": "Афганистан", "AL": "Албания", "DZ": "Алжир", "AR": "Аргентина",
    "AM": "Армения", "AU": "Австралия", "AT": "Австрия", "AZ": "Азербайджан",
    "BY": "Беларусь", "BE": "Бельгия", "BR": "Бразилия", "BG": "Болгария",
    "CA": "Канада", "CL": "Чили", "CN": "Китай", "CO": "Колумбия",
    "HR": "Хорватия", "CZ": "Чехия", "DK": "Дания", "EG": "Египет",
    "EE": "Эстония", "FI": "Финляндия", "FR": "Франция", "GE": "Грузия",
    "DE": "Германия", "GR": "Греция", "HK": "Гонконг", "HU": "Венгрия",
    "IN": "Индия", "ID": "Индонезия", "IR": "Иран", "IQ": "Ирак",
    "IE": "Ирландия", "IL": "Израиль", "IT": "Италия", "JP": "Япония",
    "KZ": "Казахстан", "KG": "Кыргызстан", "LV": "Латвия", "LT": "Литва",
    "LU": "Люксембург", "MY": "Малайзия", "MX": "Мексика", "MD": "Молдова",
    "NL": "Нидерланды", "NZ": "Новая Зеландия", "NO": "Норвегия",
    "PK": "Пакистан", "PE": "Перу", "PH": "Филиппины", "PL": "Польша",
    "PT": "Португалия", "RO": "Румыния", "RU": "Россия", "SA": "Саудовская Аравия",
    "RS": "Сербия", "SG": "Сингапур", "SK": "Словакия", "SI": "Словения",
    "ZA": "Южная Африка", "KR": "Южная Корея", "ES": "Испания", "SE": "Швеция",
    "CH": "Швейцария", "TW": "Тайвань", "TJ": "Таджикистан", "TH": "Таиланд",
    "TN": "Тунис", "TR": "Турция", "TM": "Туркменистан", "UA": "Украина",
    "GB": "Великобритания", "US": "США", "UZ": "Узбекистан", "VN": "Вьетнам",
}

_ISO2_TO_ALPHA3: dict[str, str] = {
    "AF": "AFG", "AL": "ALB", "DZ": "DZA", "AR": "ARG", "AM": "ARM", "AU": "AUS",
    "AT": "AUT", "AZ": "AZE", "BY": "BLR", "BE": "BEL", "BR": "BRA", "BG": "BGR",
    "CA": "CAN", "CL": "CHL", "CN": "CHN", "CO": "COL", "HR": "HRV", "CZ": "CZE",
    "DK": "DNK", "EG": "EGY", "EE": "EST", "FI": "FIN", "FR": "FRA", "GE": "GEO",
    "DE": "DEU", "GR": "GRC", "HK": "HKG", "HU": "HUN", "IN": "IND", "ID": "IDN",
    "IR": "IRN", "IQ": "IRQ", "IE": "IRL", "IL": "ISR", "IT": "ITA", "JP": "JPN",
    "KZ": "KAZ", "KG": "KGZ", "LV": "LVA", "LT": "LTU", "LU": "LUX", "MY": "MYS",
    "MX": "MEX", "MD": "MDA", "NL": "NLD", "NZ": "NZL", "NO": "NOR", "PK": "PAK",
    "PE": "PER", "PH": "PHL", "PL": "POL", "PT": "PRT", "RO": "ROU", "RU": "RUS",
    "SA": "SAU", "RS": "SRB", "SG": "SGP", "SK": "SVK", "SI": "SVN", "ZA": "ZAF",
    "KR": "KOR", "ES": "ESP", "SE": "SWE", "CH": "CHE", "TW": "TWN", "TJ": "TJK",
    "TH": "THA", "TN": "TUN", "TR": "TUR", "TM": "TKM", "UA": "UKR", "GB": "GBR",
    "US": "USA", "UZ": "UZB", "VN": "VNM",
}

_ALPHA3_TO_ISO2: dict[str, str] = {
    alpha3: iso2 for iso2, alpha3 in _ISO2_TO_ALPHA3.items()
}

_RUSSIAN_TO_ALPHA3: dict[str, str] = {
    russian.lower(): _ISO2_TO_ALPHA3[iso2]
    for iso2, russian in _ISO_TO_RUSSIAN.items()
    if iso2 in _ISO2_TO_ALPHA3
}

_UPPER_RUSSIAN_TO_NORMAL: dict[str, str] = {
    russian.upper(): russian
    for russian in _ISO_TO_RUSSIAN.values()
}

_ENGLISH_TO_ALPHA3: dict[str, str] = {
    "germany": "DEU",
    "kyrgyzstan": "KGZ",
    "kyrgyz republic": "KGZ",
    "china": "CHN",
    "russia": "RUS",
    "turkey": "TUR",
    "kazakhstan": "KAZ",
    "uzbekistan": "UZB",
    "sweden": "SWE",
    "france": "FRA",
    "italy": "ITA",
    "usa": "USA",
    "united states": "USA",
}

_ENGLISH_TO_RUSSIAN: dict[str, str] = {
    english: _ISO_TO_RUSSIAN[_ALPHA3_TO_ISO2[alpha3]]
    for english, alpha3 in _ENGLISH_TO_ALPHA3.items()
    if alpha3 in _ALPHA3_TO_ISO2 and _ALPHA3_TO_ISO2[alpha3] in _ISO_TO_RUSSIAN
}

_COMMON_CURRENCY_NAMES: dict[str, str] = {
    "EUR": "Euro",
    "USD": "US Dollar",
    "CNY": "Chinese Yuan",
    "RUB": "Russian Ruble",
    "KGS": "Kyrgyzstani Som",
    "KZT": "Kazakhstani Tenge",
    "GBP": "British Pound",
    "CHF": "Swiss Franc",
}

_CURRENCY_SYMBOL_TO_CODE: dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "¥": "CNY",
    "₽": "RUB",
    "£": "GBP",
}

_CURRENCY_TEXT_TO_CODE: dict[str, str] = {
    "euro": "EUR",
    "евро": "EUR",
    "us dollar": "USD",
    "dollar": "USD",
    "доллар": "USD",
    "yuan": "CNY",
    "юань": "CNY",
    "ruble": "RUB",
    "рубль": "RUB",
    "som": "KGS",
    "сом": "KGS",
    "tenge": "KZT",
    "тенге": "KZT",
    "pound": "GBP",
    "фунт": "GBP",
    "franc": "CHF",
    "франк": "CHF",
}

# ISO 3166-1 numeric codes (mirrors the ISO-2 keys above)
_ISO_TO_NUMERIC: dict[str, int] = {
    "AF": 4,   "AL": 8,   "DZ": 12,  "AR": 32,  "AM": 51,  "AU": 36,
    "AT": 40,  "AZ": 31,  "BY": 112, "BE": 56,  "BR": 76,  "BG": 100,
    "CA": 124, "CL": 152, "CN": 156, "CO": 170, "HR": 191, "CZ": 203,
    "DK": 208, "EG": 818, "EE": 233, "FI": 246, "FR": 250, "GE": 268,
    "DE": 276, "GR": 300, "HK": 344, "HU": 348, "IN": 356, "ID": 360,
    "IR": 364, "IQ": 368, "IE": 372, "IL": 376, "IT": 380, "JP": 392,
    "KZ": 398, "KG": 417, "LV": 428, "LT": 440, "LU": 442, "MY": 458,
    "MX": 484, "MD": 498, "NL": 528, "NZ": 554, "NO": 578, "PK": 586,
    "PE": 604, "PH": 608, "PL": 616, "PT": 620, "RO": 642, "RU": 643,
    "SA": 682, "RS": 688, "SG": 702, "SK": 703, "SI": 705, "ZA": 710,
    "KR": 410, "ES": 724, "SE": 752, "CH": 756, "TW": 158, "TJ": 762,
    "TH": 764, "TN": 788, "TR": 792, "TM": 795, "UA": 804, "GB": 826,
    "US": 840, "UZ": 860, "VN": 704,
}

# Reverse lookup: Russian name → numeric code (built once at import time)
_RUSSIAN_TO_NUMERIC: dict[str, int] = {
    rus.lower(): _ISO_TO_NUMERIC[iso]
    for iso, rus in _ISO_TO_RUSSIAN.items()
    if iso in _ISO_TO_NUMERIC
}

_NUMERIC_TO_RUSSIAN: dict[int, str] = {
    numeric: _ISO_TO_RUSSIAN[iso]
    for iso, numeric in _ISO_TO_NUMERIC.items()
    if iso in _ISO_TO_RUSSIAN
}


def resolve_country(raw: str | None) -> str | None:
    """Map ISO-2/ISO-3 country code to Russian name. Returns original value if not mapped."""
    if not raw:
        return raw
    text = str(raw).strip()
    code = text.upper()
    if code in _ISO_TO_RUSSIAN:
        return _ISO_TO_RUSSIAN[code]
    iso2 = _ALPHA3_TO_ISO2.get(code)
    if iso2:
        return _ISO_TO_RUSSIAN.get(iso2, raw)
    if code in _UPPER_RUSSIAN_TO_NORMAL:
        return _UPPER_RUSSIAN_TO_NORMAL[code]
    english_mapped = _ENGLISH_TO_RUSSIAN.get(text.lower())
    if english_mapped:
        return english_mapped
    return raw


def resolve_country_alpha3(raw: str | None) -> str | None:
    """Return ISO 3166-1 alpha-3 code from ISO-2, ISO-3, Russian or common English names."""
    if not raw:
        return None
    text = str(raw).strip()
    upper = text.upper()
    if upper in _ALPHA3_TO_ISO2:
        return upper
    if upper in _ISO2_TO_ALPHA3:
        return _ISO2_TO_ALPHA3[upper]
    resolved = _RUSSIAN_TO_ALPHA3.get(text.lower())
    if resolved:
        return resolved
    return _ENGLISH_TO_ALPHA3.get(text.lower())


def resolve_country_code(raw: str | None) -> int | None:
    """
    Return ISO 3166-1 numeric code for a country given either:
      - ISO-2 code  ("SE"      → 752)
      - Russian name ("Швеция" → 752)
    Returns None if not found.
    """
    if not raw:
        return None
    s = str(raw).strip()
    # Try ISO-2 first (short string)
    if len(s) <= 3:
        numeric = _ISO_TO_NUMERIC.get(s.upper())
        if numeric is not None:
            return numeric
    # Try Russian name (case-insensitive)
    return _RUSSIAN_TO_NUMERIC.get(s.lower())


def resolve_country_from_numeric(raw: int | str | None) -> str | None:
    """Map ISO 3166-1 numeric code to Russian country name."""
    if raw is None:
        return None
    try:
        numeric = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return _NUMERIC_TO_RUSSIAN.get(numeric)


def finalize_items(items: list[dict], currency_db: list[dict]) -> list[dict]:
    """
    Post-process extracted items:
      - normalise whitespace in description
      - resolve currency code/name from DB
      - map ISO country code → Russian name in country_origin
      - ensure hs_code field is present
    Mirrors Node 1765342175106 logic.
    """
    final = []
    for item in items:
        # Clean description
        desc = item.get("description", "")
        desc = re.sub(r"\s+", " ", desc).strip()
        item["description"] = desc

        # Resolve currency
        raw_val = item.get("currency_code") or item.get("currency_name")
        ccode, cname = resolve_currency(raw_val, currency_db)
        if not ccode and isinstance(raw_val, str):
            maybe_code = raw_val.strip().upper()
            if maybe_code in _COMMON_CURRENCY_NAMES:
                ccode = maybe_code
                cname = _COMMON_CURRENCY_NAMES[maybe_code]
        if ccode:
            item["currency_code"] = ccode
            item["currency_name"] = cname or _COMMON_CURRENCY_NAMES.get(ccode) or ccode

        # Map ISO country code → Russian name (e.g. "DE" → "Германия")
        # and fill country_origin_code when missing/null
        raw_origin = item.get("country_origin")
        if raw_origin:
            mapped = resolve_country(raw_origin)
            if mapped and mapped != raw_origin:
                item["country_origin"] = mapped

        raw_sender = item.get("country_sender")
        if raw_sender:
            mapped_sender = resolve_country(raw_sender)
            if mapped_sender and mapped_sender != raw_sender:
                item["country_sender"] = mapped_sender

        existing_code = item.get("country_origin_code")
        existing_code_text = str(existing_code).strip() if existing_code is not None else ""
        resolved_code = resolve_country_alpha3(existing_code_text)
        if resolved_code is None:
            resolved_code = resolve_country_alpha3(raw_origin)
        if resolved_code is None:
            resolved_code = resolve_country_alpha3(item.get("country_origin"))
        if resolved_code is not None:
            item["country_origin_code"] = resolved_code

        quantity = _to_float(item.get("quantity"))
        price = _to_float(item.get("price"))
        cost = _to_float(item.get("cost"))
        if cost is None and quantity is not None and price is not None:
            item["cost"] = _format_decimal(quantity * price)
        elif price is None and cost is not None and quantity not in (None, 0):
            item["price"] = _format_decimal(cost / quantity)

        # Ensure hs_code
        if "hs_code" not in item:
            item["hs_code"] = None

        final.append(item)

    return final


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(" ", "")
    if not text or text.lower() in {"null", "none", "-"}:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _format_decimal(value: float) -> int | float:
    rounded = round(value, 6)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded
