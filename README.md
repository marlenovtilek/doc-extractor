# doc-extractor

Stateless FastAPI service for structured invoice extraction.

It is designed to sit behind `docai` as a dedicated extraction backend:
- `docai` keeps upload, OCR, request/task lifecycle, storage, UI
- `doc-extractor` receives `ocr_draft` and returns structured `items`

## What It Does

Pipeline:
1. Clean noisy OCR
2. Parse header/footer metadata
3. Run primary model
4. Validate / repair JSON
5. Fallback to secondary model if needed
6. Normalize, deduplicate, and finalize items

The service currently supports only:
- `document_code = "04021"`

## API

### `GET /api/health/`

Returns runtime health.

Example:

```json
{
  "status": "ok",
  "database": {
    "status": "skipped",
    "detail": "Stateless FastAPI mode"
  },
  "llm_api": {
    "status": "ok",
    "model": "gpt-oss-120b",
    "provider": "Cerebras"
  }
}
```

### `POST /api/extract/`

Request:

```json
{
  "document_code": "04021",
  "ocr_draft": "raw OCR text here",
  "model": "cerebras"
}
```

Response:

```json
{
  "status": "success",
  "document_code": "04021",
  "model_id": "gpt-oss-120b",
  "items": [
    {
      "position": 1,
      "description": "Item",
      "hs_code": "85181090",
      "quantity": 1.0,
      "unit": "pcs",
      "cost": 10.0,
      "price": 10.0
    }
  ],
  "count": 1,
  "metrics": {
    "primary_valid": true,
    "fallback_used": false
  },
  "error": ""
}
```

If extraction fails, the endpoint returns `500` with an error detail.

## Supported Models

Aliases:
- `cerebras` -> `gpt-oss-120b`
- `gemini` -> `gemini-2.5-flash`

You can also pass a raw model id.

## Local Run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn fastapi_app.main:app --reload --host 0.0.0.0 --port 8000
```

Service:
- `http://127.0.0.1:8000/api/health/`
- `http://127.0.0.1:8000/api/extract/`

## Docker

```bash
cp .env.example .env
docker compose up --build
```

## Environment

Required provider keys depend on the model you use.

Main variables:
- `LLM_MODEL_PRIMARY`
- `LLM_MODEL_FALLBACK`
- `CEREBRAS_BASE_URL`
- `CEREBRAS_API_KEY`
- `LANGEXTRACT_API_KEY`
- `LLM_MAX_WORKERS_CEREBRAS`
- `LLM_MAX_CHAR_BUFFER_CEREBRAS`
- `CEREBRAS_MAX_RETRIES`
- `CEREBRAS_RETRY_BASE_DELAY_S`
- `LLM_MAX_CHAR_BUFFER`
- `LLM_MAX_WORKERS_GEMINI`
- `CURRENCY_DB_JSON`

## Tests

```bash
python -m unittest discover -s extractor -p 'tests*.py'
```

## Integration With docai

Recommended `docai` integration point:
- replace current Dify extraction call inside `task_field_extraction.py`
- keep OCR, request/task state, and result storage in `docai`
- call this service with:

```json
{
  "document_code": "04021",
  "ocr_draft": "...",
  "model": "cerebras"
}
```

And map returned `items` directly into `docai`'s existing save step.
