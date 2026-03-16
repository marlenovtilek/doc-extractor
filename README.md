# doc-extractor

Stateless FastAPI service for structured document extraction.

It is designed to sit behind `docai` as a dedicated extraction backend:
- `docai` keeps upload, OCR, request/task lifecycle, storage, UI
- `doc-extractor` receives `document_code + ocr_draft` and routes to the matching handler

## What It Does

Pipeline:
1. Clean noisy OCR
2. Parse header/footer metadata
3. Run primary model
4. Validate / repair JSON
5. Fallback to secondary model if needed
6. Normalize, deduplicate, and finalize the extracted result

Current registered handler:
- `document_code = "04021"` -> `invoice`

The service is structured for more handlers via `extractor/documents/*` and `extractor/documents/registry.py`.

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
  "result_type": "table",
  "data": {
    "fields": {},
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
    "count": 1
  },
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
- `gemini-flash` -> `gemini-2.5-flash`
- `gemini-pro` -> `gemini-2.5-pro`
- `openai` -> `OPENAI_MODEL_DEFAULT`
- `ollama` -> `OLLAMA_MODEL_DEFAULT`

You can also pass:
- a raw model id when the provider can be inferred, for example `gpt-4o-mini`, `gemini-2.5-flash`, `qwen2.5:7b`
- an explicit provider spec: `provider::model_id`

Examples:
- `cerebras`
- `gemini`
- `gemini-flash`
- `gemini-pro`
- `gemini::gemini-2.5-pro`
- `openai::gpt-4o-mini`
- `ollama::mistral:7b`

## Local Run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_ORGANIZATION`
- `OPENAI_MODEL_DEFAULT`
- `OLLAMA_BASE_URL`
- `OLLAMA_API_KEY`
- `OLLAMA_MODEL_DEFAULT`
- `OLLAMA_TIMEOUT_S`
- `CEREBRAS_BASE_URL`
- `CEREBRAS_API_KEY`
- `LANGEXTRACT_API_KEY`
- `LLM_MAX_WORKERS_CEREBRAS`
- `LLM_MAX_CHAR_BUFFER_CEREBRAS`
- `CEREBRAS_MAX_RETRIES`
- `CEREBRAS_RETRY_BASE_DELAY_S`
- `LLM_MAX_CHAR_BUFFER`
- `LLM_MAX_WORKERS_GEMINI`
- `LLM_MAX_WORKERS_OPENAI`
- `CURRENCY_DB_JSON`

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

## Integration With docai

Recommended `docai` integration point:
- replace the current extraction branch with a call to this service
- keep OCR, request/task state, and result storage in `docai`
- branch in `docai` by `document_code`, then call this service with:

```json
{
  "document_code": "04021",
  "ocr_draft": "...",
  "model": "cerebras"
}
```

For table-style documents, map returned `data.items` or top-level `items` into `docai`'s save step.
