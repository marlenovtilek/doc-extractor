# doc-extractor

Stateless FastAPI service for structured document extraction.

It is designed to sit behind `docai` as a dedicated extraction backend:
- `docai` keeps upload, OCR, request/task lifecycle, storage, UI
- `doc-extractor` receives `document_code + ocr_draft` and routes to the matching handler

## What It Does

Pipeline:
1. Clean noisy OCR
2. Route the request to the matching document handler
3. Run parser-first or model-assisted extraction, depending on the document type
4. Validate / repair structured output
5. Normalize, deduplicate, and finalize the extracted result
6. Return a stateless payload for API clients or the built-in web UI

Current document coverage is defined in [`extractor/documents/registry.py`](./extractor/documents/registry.py) and includes:
- `04021` -> Invoice
- `09022` -> Technical Document
- `03011` -> Contract
- `00012` -> Supply Contract
- `11019` -> Power of Attorney
- `00002` -> CMR
- `9012` -> Passport
- `22222` -> Protocol
- certificate / declaration / veterinary / phytosanitary / fallback-style handlers such as `11111`, `11116`, `01207`, `01201`, `11014`, `09999`, `10999`, and `ELSE`

The invoice flow is the most specialized pipeline in the service. It supports:
- OCR cleanup and table rehydration
- parser-first extraction with selective line-level assist
- deduplication / shadow-row pruning
- review metadata for low-confidence rows

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
    "execution_path": {
      "mode": "parser_first"
    }
  },
  "error": ""
}
```

If extraction fails, the endpoint returns `500` with an error detail.

### `GET /api/meta/`

Returns registered document definitions, available model aliases/families, provider readiness, and current defaults.

### Web endpoints

The built-in web UI is served from:
- `GET /`

Supporting web endpoints:
- `GET /web/health/`
- `GET /web/meta/`
- `POST /web/extract/`
- `POST /web/jobs/`
- `GET /web/jobs/{job_id}/`
- `POST /web/jobs/{job_id}/cancel/`

`/api/*` endpoints can be protected with `DOC_EXTRACTOR_API_TOKEN`. `/web/*` endpoints stay open for the local operator UI.

## Supported Models

Provider catalogs come from `.env`:
- `GEMINI_MODELS`
- `GPT_MODELS`
- `OLLAMA_MODELS`
- `CEREBRAS_MODELS`

You can also pass:
- a raw model id when the provider can be inferred, for example `gpt-4o-mini`, `gemini-2.5-flash`, `qwen2.5:7b`
- an explicit provider spec: `provider::model_id`

Examples:
- `gemini`
- `openai`
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
- `http://127.0.0.1:8000/`

## Docker

```bash
cp .env.example .env
docker compose up --build
```

## Environment

Required provider keys depend on the model you use.

Main variables:
- `DOC_EXTRACTOR_API_TOKEN`
- `LLM_MODEL_PRIMARY`
- `LLM_MODEL_FALLBACK`
- `GEMINI_MODELS`
- `GPT_MODELS`
- `OLLAMA_MODELS`
- `CEREBRAS_MODELS`
- `OPENAI_API_KEY`
- `OLLAMA_BASE_URL`
- `OLLAMA_TIMEOUT_S`
- `CEREBRAS_BASE_URL`
- `CEREBRAS_API_KEY`
- `GEMINI_API_KEY`
- `LLM_MAX_CHAR_BUFFER`
- `WEB_JOB_MAX_WORKERS`
- `WEB_JOB_RETENTION_S`
- `WEB_JOB_MAX_STORED`
- `CURRENCY_DB_JSON`

## Tests

```bash
python -m compileall app extractor
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

For invoice-style responses, `data` may also include review-oriented helpers such as:
- `review_summary`
- `top_review_items`

These are intended for operator-facing UI flows and manual QA queues.
