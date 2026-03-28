from __future__ import annotations


def render_home_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>doc-extractor</title>
    <style>
      :root {
        --bg: #f4f0e8;
        --panel: #fffdf8;
        --ink: #1c1a16;
        --muted: #6d6458;
        --line: #d9cfbf;
        --accent: #945b2d;
        --accent-2: #e6d6bf;
        --success: #2f6b40;
        --error: #9d2f2f;
        --shadow: 0 18px 40px rgba(37, 26, 15, 0.08);
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(230, 214, 191, 0.8), transparent 26%),
          linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
      }

      .page {
        max-width: 1460px;
        margin: 0 auto;
        padding: 14px;
      }

      .workspace-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.7fr) minmax(360px, 1fr);
        gap: 10px;
        margin-bottom: 10px;
        align-items: start;
      }

      .stack {
        display: grid;
        gap: 10px;
        align-content: start;
      }

      .hero-card,
      .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        box-shadow: var(--shadow);
      }

      .hero-card {
        padding: 16px 18px;
        position: relative;
        overflow: hidden;
      }

      .hero-card::after {
        content: "";
        position: absolute;
        inset: auto -40px -60px auto;
        width: 220px;
        height: 220px;
        background: radial-gradient(circle, rgba(148, 91, 45, 0.16), transparent 70%);
        pointer-events: none;
      }

      .eyebrow {
        color: var(--accent);
        font-size: 10px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        margin-bottom: 6px;
      }

      h1 {
        margin: 0 0 6px;
        font-size: clamp(24px, 2.8vw, 34px);
        line-height: 1;
        letter-spacing: -0.04em;
        white-space: nowrap;
      }

      .lead {
        margin: 0;
        max-width: 64ch;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.35;
      }

      .hero-top {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 6px;
        position: relative;
        z-index: 1;
      }

      .hero-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
      }

      .hero-copy {
        max-width: 640px;
      }

      .runtime-strip {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 10px;
        position: relative;
        z-index: 1;
      }

      .runtime-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 5px 9px;
        border-radius: 999px;
        background: #faf6ef;
        border: 1px solid #eee3d3;
        color: var(--muted);
        font-size: 10px;
      }

      .runtime-chip strong {
        color: var(--ink);
      }

      .connections-panel {
        margin-bottom: 0;
      }

      .provider-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 6px;
      }

      .provider-card {
        flex: 1 1 220px;
        min-width: 0;
        padding: 8px 10px;
        border-radius: 12px;
        background: #fbf8f2;
        border: 1px solid #eee3d3;
      }

      .provider-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 4px;
      }

      .provider-name {
        font-size: 12px;
        font-weight: 600;
      }

      .provider-status {
        display: inline-flex;
        align-items: center;
        padding: 3px 7px;
        border-radius: 999px;
        font-size: 10px;
        border: 1px solid #eee3d3;
        background: #f5ecdf;
        color: var(--accent);
      }

      .provider-status.ready {
        color: var(--success);
        background: #eef7f0;
        border-color: #d5e7d9;
      }

      .provider-status.missing {
        color: var(--error);
        background: #fbefef;
        border-color: #ecd3d3;
      }

      .provider-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        font-size: 10px;
        color: var(--muted);
      }

      .provider-detail {
        margin-top: 6px;
        padding-top: 6px;
        border-top: 1px dashed #e8dcc8;
        font-size: 10px;
        color: var(--muted);
        min-height: 0;
      }

      .panel {
        padding: 12px;
      }

      .summary-panel {
        display: flex;
        flex-direction: column;
      }

      .form-grid {
        display: grid;
        gap: 8px;
      }

      .toolbar-row {
        display: grid;
        grid-template-columns:
          minmax(170px, 210px)
          minmax(150px, 180px)
          minmax(210px, 260px)
          minmax(0, 1fr);
        gap: 8px;
        align-items: end;
      }

      .toolbar-actions {
        display: flex;
        justify-content: flex-end;
      }

      label {
        display: block;
        font-size: 11px;
        color: var(--muted);
        margin-bottom: 5px;
      }

      input,
      select,
      textarea,
      button {
        font: inherit;
      }

      input[type="text"],
      select,
      textarea {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: #fff;
        color: var(--ink);
        padding: 9px 11px;
      }

      textarea {
        min-height: 190px;
        resize: vertical;
        line-height: 1.35;
      }

      .button-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
        justify-content: flex-end;
        min-height: 40px;
      }

      .button-row button {
        white-space: nowrap;
      }

      button {
        border: 0;
        border-radius: 999px;
        padding: 8px 12px;
        cursor: pointer;
        transition: transform 0.14s ease, opacity 0.14s ease;
      }

      button:hover { transform: translateY(-1px); }
      button:disabled { opacity: 0.6; cursor: wait; transform: none; }

      .primary {
        background: var(--accent);
        color: #fff;
      }

      .secondary {
        background: var(--accent-2);
        color: var(--ink);
      }

      .ghost-link {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 32px;
        padding: 7px 12px;
        border-radius: 999px;
        border: 1px solid #e7dac7;
        background: #fbf7f0;
        color: var(--ink);
        text-decoration: none;
        font-size: 12px;
        transition: transform 0.14s ease, background 0.14s ease;
      }

      .ghost-link:hover {
        transform: translateY(-1px);
        background: #f6efe4;
      }

      .alert {
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid #ecd3d3;
        background: #fbefef;
        color: var(--error);
        font-size: 12px;
        line-height: 1.4;
      }

      .alert strong {
        display: block;
        margin-bottom: 3px;
      }

      .results-grid {
        display: grid;
        gap: 10px;
      }

      .results-top-grid {
        display: grid;
        grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
        gap: 10px;
        align-items: start;
      }

      .aux-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 10px;
      }

      .section-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 8px;
      }

      .section-head h2,
      .section-head h3 {
        margin: 0;
        font-size: 15px;
      }

      .mono {
        font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
        font-size: 11px;
      }

      .pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 4px 8px;
        border-radius: 999px;
        background: #f5ecdf;
        color: var(--accent);
        font-size: 10px;
      }

      .cards {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 6px;
      }

      .summary-panel .cards {
        flex: 1;
        align-content: stretch;
      }

      .selection-note {
        margin-top: 8px;
        padding: 8px 10px;
        border-radius: 12px;
        background: #fbf8f2;
        border: 1px solid #eee3d3;
        font-size: 11px;
        color: var(--muted);
        line-height: 1.35;
      }

      .selection-note strong {
        color: var(--ink);
      }

      .card {
        padding: 8px 9px;
        border-radius: 12px;
        background: #fbf8f2;
        border: 1px solid #eee3d3;
      }

      .summary-panel .card {
        min-height: 52px;
      }

      .card-label {
        color: var(--muted);
        font-size: 10px;
        margin-bottom: 3px;
      }

      .card-value {
        font-size: 22px;
        letter-spacing: -0.04em;
      }

      .summary-panel .card-label {
        font-size: 11px;
      }

      .summary-panel .card-value {
        font-size: 13px;
        line-height: 1.15;
        letter-spacing: -0.02em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .kv {
        display: grid;
        gap: 5px;
      }

      .kv-row {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 7px 9px;
        border-radius: 12px;
        background: #fbf8f2;
        border: 1px solid #eee3d3;
      }

      .review-panel {
        display: grid;
        gap: 10px;
      }

      .review-strip {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }

      .review-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid #eee3d3;
        background: #fbf8f2;
        color: var(--muted);
        font-size: 11px;
      }

      .review-chip strong {
        color: var(--ink);
      }

      .review-chip.high {
        background: #fbefef;
        border-color: #ecd3d3;
        color: var(--error);
      }

      .review-chip.medium {
        background: #f8f2e8;
        border-color: #e7dac7;
        color: var(--accent);
      }

      .review-list {
        display: grid;
        gap: 8px;
      }

      .review-item {
        padding: 10px 11px;
        border-radius: 12px;
        border: 1px solid #eee3d3;
        background: #fbf8f2;
        cursor: pointer;
        transition: transform 0.14s ease, border-color 0.14s ease, background 0.14s ease;
      }

      .review-item:hover {
        transform: translateY(-1px);
        border-color: #dcc8ae;
        background: #fffaf2;
      }

      .review-item-top {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: flex-start;
        margin-bottom: 6px;
      }

      .review-item-title {
        font-size: 12px;
        font-weight: 600;
        line-height: 1.3;
      }

      .review-badge {
        display: inline-flex;
        align-items: center;
        padding: 3px 7px;
        border-radius: 999px;
        font-size: 10px;
        border: 1px solid #eee3d3;
        white-space: nowrap;
      }

      .review-badge.high {
        color: var(--error);
        background: #fbefef;
        border-color: #ecd3d3;
      }

      .review-badge.medium {
        color: var(--accent);
        background: #f8f2e8;
        border-color: #e7dac7;
      }

      .review-item-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        color: var(--muted);
        font-size: 10px;
      }

      .table-wrap {
        overflow: auto;
        border: 1px solid #eee3d3;
        border-radius: 14px;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        min-width: 840px;
        background: #fff;
      }

      th, td {
        padding: 7px 9px;
        border-bottom: 1px solid #f0e7da;
        text-align: left;
        vertical-align: top;
        font-size: 11px;
      }

      tr.row-review-high td {
        background: #fff4f4;
      }

      tr.row-review-medium td {
        background: #fff9ef;
      }

      tr.row-focused td {
        box-shadow: inset 0 0 0 9999px rgba(148, 91, 45, 0.12);
      }

      th {
        position: sticky;
        top: 0;
        background: #f8f2e8;
        z-index: 1;
      }

      pre {
        margin: 0;
        padding: 10px;
        border-radius: 14px;
        background: #151311;
        color: #f7f1e8;
        overflow: auto;
        max-height: 220px;
      }

      .muted { color: var(--muted); }
      .ok { color: var(--success); }
      .bad { color: var(--error); }
      .hidden { display: none; }

      @media (max-width: 1100px) {
        .workspace-grid,
        .aux-grid,
        .results-top-grid {
          grid-template-columns: 1fr;
        }
        .cards {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .toolbar-row {
          grid-template-columns: 1fr 1fr;
        }
        .toolbar-row .toolbar-actions {
          grid-column: 1 / -1;
          justify-content: flex-start;
        }
        h1 {
          white-space: normal;
        }
      }

      @media (max-width: 720px) {
        .page { padding: 12px; }
        .toolbar-row,
        .cards {
          grid-template-columns: 1fr;
        }
        .hero-top {
          flex-direction: column;
          align-items: flex-start;
        }
        .hero-actions {
          justify-content: flex-start;
        }
        textarea { min-height: 180px; }
      }
    </style>
  </head>
  <body>
    <div class="page">
      <section class="workspace-grid">
        <div class="stack">
          <div class="hero-card">
            <div class="hero-top">
              <div class="hero-copy">
                <div class="eyebrow">doc-extractor</div>
                <h1>Doc-Extractor</h1>
                <p class="lead">
                  Paste OCR text, pick a document handler and model, then inspect the extracted
                  fields, rows, metrics, and raw JSON in one place.
                </p>
              </div>
              <div class="hero-actions">
                <a class="ghost-link mono" href="/docs" target="_blank" rel="noreferrer">API Docs</a>
                <span id="health-pill" class="pill mono">Loading...</span>
              </div>
            </div>
            <div id="runtime-strip" class="runtime-strip"></div>
          </div>
          <div class="panel">
            <div class="section-head">
              <h2>Run Extraction</h2>
              <span class="muted mono">POST /api/extract/</span>
            </div>
            <form id="extract-form" class="form-grid">
              <div class="toolbar-row">
                <div>
                  <label for="document_code">Document Code</label>
                  <select id="document_code" name="document_code"></select>
                </div>
                <div>
                  <label for="model_family">Model Family</label>
                  <select id="model_family" name="model_family"></select>
                </div>
                <div>
                  <label for="model">Model</label>
                  <select id="model" name="model"></select>
                </div>
                <div class="toolbar-actions">
                  <div class="button-row">
                    <button id="submit-button" class="primary" type="submit">Run Extraction</button>
                    <button id="cancel-button" class="secondary" type="button" disabled>Cancel</button>
                    <button id="clear-button" class="secondary" type="button">Clear</button>
                  </div>
                </div>
              </div>

              <div id="error-banner" class="alert hidden">
                <strong>Extraction failed</strong>
                <span id="error-message">Unknown error.</span>
              </div>

              <div>
                <label for="ocr_draft">OCR Draft</label>
                <textarea
                  id="ocr_draft"
                  name="ocr_draft"
                  spellcheck="false"
                  placeholder="Paste raw OCR text here..."
                ></textarea>
              </div>
            </form>
          </div>
        </div>
        <div class="stack">
          <div class="panel connections-panel">
            <div class="section-head">
              <h2>Model Connections</h2>
              <span class="muted mono">provider readiness</span>
            </div>
            <div id="provider-grid" class="provider-grid"></div>
          </div>
          <div class="panel summary-panel">
            <div class="section-head">
              <h2>Summary</h2>
              <span id="result-pill" class="pill mono">No result yet</span>
            </div>
            <div id="summary-cards" class="cards">
              <div class="card"><div class="card-label">Document</div><div id="summary-document" class="card-value">-</div></div>
              <div class="card"><div class="card-label">Model</div><div id="summary-model" class="card-value">-</div></div>
              <div class="card"><div class="card-label">Rows</div><div id="summary-count" class="card-value">0</div></div>
              <div class="card"><div class="card-label">Tokens</div><div id="summary-tokens" class="card-value">-</div></div>
              <div class="card"><div class="card-label">Duration</div><div id="summary-duration" class="card-value">-</div></div>
              <div class="card"><div class="card-label">Fallback</div><div id="summary-fallback" class="card-value">-</div></div>
            </div>
            <div id="summary-selection" class="selection-note">
              <strong>Model Route:</strong> pending
            </div>
          </div>
        </div>
      </section>

      <section>
        <div class="results-grid">
          <div class="results-top-grid">
            <div class="panel">
              <div class="section-head">
                <h3>Fields</h3>
                <span class="muted mono">result.data.fields</span>
              </div>
              <div id="fields-view" class="kv muted">No extracted fields yet.</div>
            </div>
          </div>

          <div class="panel">
            <div class="section-head">
              <h3>Items</h3>
              <span id="items-meta" class="muted mono">0 rows</span>
            </div>
            <div id="items-view" class="table-wrap hidden"></div>
            <div id="items-empty" class="muted">No extracted rows yet.</div>
          </div>

          <div class="aux-grid">
            <div class="panel">
              <div class="section-head">
                <h3>Metrics</h3>
                <span class="muted mono">result.metrics</span>
              </div>
              <pre id="metrics-view">{}</pre>
            </div>

            <div class="panel">
              <div class="section-head">
                <h3>Raw Response</h3>
                <span class="muted mono">JSON</span>
              </div>
              <pre id="raw-view">{}</pre>
            </div>
          </div>
        </div>
      </section>
    </div>

    <script>
      let metaState = null;
      let activeJobId = null;
      let activeJobPoll = null;
      const documentSelect = document.getElementById("document_code");
      const modelFamilySelect = document.getElementById("model_family");
      const modelSelect = document.getElementById("model");
      const ocrDraftInput = document.getElementById("ocr_draft");
      const submitButton = document.getElementById("submit-button");
      const cancelButton = document.getElementById("cancel-button");
      const clearButton = document.getElementById("clear-button");
      const healthPill = document.getElementById("health-pill");
      const resultPill = document.getElementById("result-pill");
      const errorBanner = document.getElementById("error-banner");
      const errorMessage = document.getElementById("error-message");
      const runtimeStrip = document.getElementById("runtime-strip");
      const providerGrid = document.getElementById("provider-grid");
      const fieldsView = document.getElementById("fields-view");
      const itemsView = document.getElementById("items-view");
      const itemsEmpty = document.getElementById("items-empty");
      const itemsMeta = document.getElementById("items-meta");
      const metricsView = document.getElementById("metrics-view");
      const rawView = document.getElementById("raw-view");
      const summarySelection = document.getElementById("summary-selection");

      function getConfiguredFamilyModels(meta, family) {
        const selectedFamily = (meta.model_families || []).find((item) => item.provider === family);
        if (!selectedFamily) {
          return [];
        }
        return (selectedFamily.models || []).filter((item) => item.configured);
      }

      function setJson(target, value) {
        target.textContent = JSON.stringify(value, null, 2);
      }

      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }

      function stopPollingJob() {
        if (activeJobPoll) {
          clearTimeout(activeJobPoll);
          activeJobPoll = null;
        }
        activeJobId = null;
      }

      function setJobControls(isActive, isCancelling = false) {
        submitButton.disabled = isActive;
        cancelButton.disabled = !isActive || isCancelling;
        clearButton.disabled = isActive;
      }

      async function readJsonResponse(response) {
        const text = await response.text();
        if (!text) {
          return {};
        }
        try {
          return JSON.parse(text);
        } catch {
          return { detail: text };
        }
      }

      function humanizeError(message) {
        const text = String(message || "").trim();
        const lower = text.toLowerCase();

        if (
          lower.includes("insufficient_quota") ||
          lower.includes("you exceeded your current quota")
        ) {
          return "OpenAI quota exceeded. Check billing or switch to another model/provider.";
        }

        if (
          lower.includes("token_quota_exceeded") ||
          lower.includes("tokens per day limit exceeded")
        ) {
          return "Cerebras daily token quota exceeded. Wait for reset or switch to another provider.";
        }

        if (lower.includes("queue_exceeded") || lower.includes("high traffic")) {
          return "Provider is overloaded right now. Retry shortly or switch to another model.";
        }

        if (lower.includes("not configured") || lower.includes("missing_config")) {
          return "Selected provider is not configured in .env.";
        }

        if (lower.includes("unsupported model spec")) {
          return "Selected model is not supported by this service configuration.";
        }

        if (lower.includes("unsupported document_code")) {
          return "This document type is not supported by the current extractor.";
        }

        if (lower.includes("empty ocr text")) {
          return "OCR Draft is empty. Paste OCR text before running extraction.";
        }

        if (lower.includes("no valid items extracted")) {
          return "The model returned no valid rows for this OCR. Try another provider or cleaner OCR text.";
        }

        return text || "Extraction failed.";
      }

      function showError(message) {
        errorMessage.textContent = humanizeError(message);
        errorBanner.classList.remove("hidden");
      }

      function hideError() {
        errorMessage.textContent = "Unknown error.";
        errorBanner.classList.add("hidden");
      }

      function renderRuntimeStrip(health) {
        const rows = [
          ["Service", health.status || "-"],
          ["Provider", health.llm_api?.provider || "-"],
          ["Model", health.llm_api?.model || "-"],
          ["Storage", health.database?.status || "-"],
        ];

        runtimeStrip.innerHTML = rows
          .map(([label, value]) => `
            <div class="runtime-chip">
              <span>${escapeHtml(label)}</span>
              <strong class="mono">${escapeHtml(value)}</strong>
            </div>
          `)
          .join("");
      }

      function renderProviderGrid(meta) {
        const providers = Object.values(meta.providers || {});
        providerGrid.innerHTML = providers
          .map((provider) => {
            const statusClass = provider.configured ? "ready" : "missing";
            const statusLabel = provider.configured ? "ready" : "not configured";
            const detail = provider.configured ? "Configured and ready to use." : "Not configured";
            return `
              <div class="provider-card">
                <div class="provider-top">
                  <div class="provider-name">${escapeHtml(provider.label)}</div>
                  <span class="provider-status ${statusClass}">${escapeHtml(statusLabel)}</span>
                </div>
                <div class="provider-meta">
                  <div><span class="muted">Type</span> · <strong>${escapeHtml(provider.kind)}</strong></div>
                  <div><span class="muted">Default</span> · <strong class="mono">${escapeHtml(provider.default_model_id)}</strong></div>
                </div>
                <div class="provider-detail">${escapeHtml(detail)}</div>
              </div>
            `;
          })
          .join("");
      }

      function renderFields(fields) {
        const entries = Object.entries(fields || {}).filter(([, value]) => value !== null && value !== "");
        if (!entries.length) {
          fieldsView.className = "kv muted";
          fieldsView.textContent = "No extracted fields.";
          return;
        }

        fieldsView.className = "kv";
        fieldsView.innerHTML = entries
          .map(([key, value]) => `
            <div class="kv-row">
              <span class="muted">${escapeHtml(key)}</span>
              <strong class="mono">${escapeHtml(value)}</strong>
            </div>
          `)
          .join("");
      }

      function renderItems(items) {
        const rows = Array.isArray(items) ? items : [];
        itemsMeta.textContent = `${rows.length} rows`;

        if (!rows.length) {
          itemsView.classList.add("hidden");
          itemsEmpty.classList.remove("hidden");
          itemsView.innerHTML = "";
          return;
        }

        const columns = Array.from(
          rows.reduce((set, row) => {
            Object.keys(row || {}).forEach((key) => set.add(key));
            return set;
          }, new Set())
        );

        const thead = `<thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>`;
        const tbody = rows
          .map(
            (row) => {
              const priority = String(row?.review_priority || "").toLowerCase();
              const position = row?.position ?? "";
              const rowClass =
                row?.review_required && priority === "high"
                  ? "row-review-high"
                  : row?.review_required && priority === "medium"
                    ? "row-review-medium"
                    : "";
              return `
              <tr class="${rowClass}" data-position="${position}">
                ${columns
                  .map((column) => `<td>${escapeHtml(row?.[column] ?? "")}</td>`)
                  .join("")}
              </tr>
            `;
            }
          )
          .join("");

        itemsView.innerHTML = `<table>${thead}<tbody>${tbody}</tbody></table>`;
        itemsView.classList.remove("hidden");
        itemsEmpty.classList.add("hidden");
      }

      function humanizeSelectionReason(reason) {
        const value = String(reason || "").trim();
        if (!value) {
          return "no selection details";
        }

        const map = {
          user_selected_model: "selected manually in the form",
          auto_route_disabled: "auto-routing disabled, using configured defaults",
          large_or_tabular_table_document: "large or strongly tabular OCR, using table-optimized route",
          small_table_document: "small table OCR, using lower-cost default route",
          object_document: "object-style document, using default object extraction route",
        };

        return map[value] || value.replaceAll("_", " ");
      }

      function humanizeJobProgress(progress, detail) {
        const labelMap = {
          queued: "queued",
          routing: "routing",
          extracting: "extracting",
          cleaning: "cleaning OCR",
          parsing: "parsing rows",
          llm_primary: "primary model",
          llm_fallback: "fallback model",
          finalizing: "finalizing result",
          cancelling: "cancelling",
          completed: "completed",
          cancelled: "cancelled",
          failed: "failed",
        };
        const label = labelMap[String(progress || "").trim()] || String(progress || "working");
        return detail ? `${label} · ${detail}` : label;
      }

      function updateSummary(response) {
        const tokenUsage = response.metrics?.token_usage || {};
        const totalTokens =
          tokenUsage?.total?.total_tokens ??
          tokenUsage?.primary?.total_tokens ??
          tokenUsage?.fallback?.total_tokens;
        const duration = response.metrics?.t_total_s;
        const selection = response.metrics?.model_selection || {};
        const selectionMode = selection.mode || "unknown";
        const selectionModel = selection.selected_model || response.model_id || "-";
        const selectionReason = humanizeSelectionReason(selection.reason);

        document.getElementById("summary-document").textContent = response.document_code || "-";
        document.getElementById("summary-model").textContent = response.model_id || "-";
        document.getElementById("summary-count").textContent = String(response.count ?? 0);
        document.getElementById("summary-tokens").textContent =
          Number.isFinite(Number(totalTokens)) ? new Intl.NumberFormat().format(Number(totalTokens)) : "-";
        document.getElementById("summary-duration").textContent =
          Number.isFinite(Number(duration)) ? `${Number(duration).toFixed(2)}s` : "-";
        document.getElementById("summary-fallback").textContent =
          response.metrics?.fallback_used ? "Yes" : "No";
        summarySelection.innerHTML =
          `<strong>Model Route:</strong> ${escapeHtml(selectionMode)} · <span class="mono">${escapeHtml(selectionModel)}</span> · ${escapeHtml(selectionReason)}`;
      }

      function populateMeta(meta) {
        metaState = meta;
        documentSelect.innerHTML = (meta.documents || [])
          .map((item) => `<option value="${item.document_code}">${item.document_code} · ${item.label}</option>`)
          .join("");

        modelFamilySelect.innerHTML = (meta.model_families || [])
          .map((family) => {
            const suffix = family.configured ? "" : " (not configured)";
            const disabled = family.configured ? "" : " disabled";
            return `<option value="${family.provider}"${disabled}>${family.label}${suffix}</option>`;
          })
          .join("");

        if (meta.defaults?.document_code) {
          documentSelect.value = meta.defaults.document_code;
        }

        const configuredFamilies = (meta.model_families || []).filter((item) => item.configured);
        if (
          meta.defaults?.model_family &&
          configuredFamilies.some((item) => item.provider === meta.defaults.model_family)
        ) {
          modelFamilySelect.value = meta.defaults.model_family;
        } else if (configuredFamilies.length) {
          modelFamilySelect.value = configuredFamilies[0].provider;
        }

        populateModelOptions(meta, modelFamilySelect.value, meta.defaults?.model || "");
      }

      function populateModelOptions(meta, family, preferredAlias = "") {
        const configuredModels = getConfiguredFamilyModels(meta, family);
        const options = [
          `<option value="">Auto · service decides</option>`,
          ...configuredModels.map(
            (item) => `<option value="${item.alias}">${item.alias} · ${item.model_id}</option>`
          ),
        ];
        modelSelect.innerHTML = options.join("");

        if (preferredAlias && configuredModels.some((item) => item.alias === preferredAlias)) {
          modelSelect.value = preferredAlias;
        } else {
          modelSelect.value = "";
        }
      }

      function applyExtractionResponse(json) {
        resultPill.textContent = `${json.status} · ${json.result_type}`;
        resultPill.className = "pill mono ok";
        updateSummary(json);
        renderFields(json.data?.fields || {});
        renderItems(json.data?.items || json.items || []);
        setJson(metricsView, json.metrics || {});
        setJson(rawView, json);
      }

      function resetSummary() {
        document.getElementById("summary-document").textContent = "-";
        document.getElementById("summary-model").textContent = "-";
        document.getElementById("summary-count").textContent = "0";
        document.getElementById("summary-tokens").textContent = "-";
        document.getElementById("summary-duration").textContent = "-";
        document.getElementById("summary-fallback").textContent = "-";
        summarySelection.innerHTML = "<strong>Model Route:</strong> pending";
      }

      function showJobState(job) {
        const detail = humanizeJobProgress(job.progress, job.progress_detail || "");
        resultPill.textContent = `${job.status} · ${detail}`;
        resultPill.className = "pill mono";
        summarySelection.innerHTML = `<strong>Job Progress:</strong> ${detail}`;
        setJson(rawView, job);
      }

      function handleCancelledJob(job) {
        stopPollingJob();
        hideError();
        resultPill.textContent = "cancelled";
        resultPill.className = "pill mono";
        summarySelection.innerHTML = "<strong>Job Progress:</strong> cancelled by user";
        setJson(metricsView, {});
        setJson(rawView, job || { status: "cancelled" });
        setJobControls(false);
      }

      async function pollJob(jobId) {
        const response = await fetch(`/web/jobs/${jobId}/`);
        const json = await readJsonResponse(response);
        if (!response.ok) {
          throw new Error(json.detail || "Failed to read extraction job.");
        }

        if (json.status === "queued" || json.status === "running") {
          showJobState(json);
          setJobControls(true, Boolean(json.cancel_requested));
          activeJobPoll = window.setTimeout(() => {
            pollJob(jobId).catch(handleJobError);
          }, 1000);
          return;
        }

        stopPollingJob();
        setJobControls(false);

        if (json.status === "cancelled") {
          handleCancelledJob(json);
          return;
        }

        if (json.status === "completed" && json.result) {
          applyExtractionResponse(json.result);
          return;
        }

        resultPill.textContent = "failed";
        resultPill.className = "pill mono bad";
        showError(json.error || json.result?.error || "Extraction failed");
        if (json.result) {
          setJson(metricsView, json.result.metrics || {});
          setJson(rawView, json.result);
        } else {
          setJson(metricsView, {});
          setJson(rawView, { error: json.error || "Extraction failed" });
        }
      }

      function handleJobError(error) {
        stopPollingJob();
        setJobControls(false);
        resultPill.textContent = "failed";
        resultPill.className = "pill mono bad";
        showError(error.message || "Extraction failed");
        setJson(metricsView, {});
        setJson(rawView, { error: error.message || "Extraction failed" });
      }

      async function loadMeta() {
        const [healthRes, metaRes] = await Promise.all([
          fetch("/web/health/"),
          fetch("/web/meta/"),
        ]);

        if (!healthRes.ok) {
          const payload = await readJsonResponse(healthRes);
          throw new Error(payload.detail || "Failed to load service health.");
        }
        if (!metaRes.ok) {
          const payload = await readJsonResponse(metaRes);
          throw new Error(payload.detail || "Failed to load service metadata.");
        }

        const health = await readJsonResponse(healthRes);
        const meta = await readJsonResponse(metaRes);

        healthPill.textContent = `${health.status} · ${health.llm_api?.provider || "-"}`;
        healthPill.className = `pill mono ${health.status === "ok" ? "ok" : "bad"}`;
        renderRuntimeStrip(health);
        populateMeta(meta);
        renderProviderGrid(meta);
      }

      async function runExtraction(event) {
        event.preventDefault();
        stopPollingJob();
        setJobControls(true, true);
        resultPill.textContent = "queued";
        resultPill.className = "pill mono";
        hideError();
        summarySelection.innerHTML = "<strong>Job Progress:</strong> queued";

        const payload = {
          document_code: documentSelect.value,
          model: modelSelect.value || null,
          ocr_draft: ocrDraftInput.value,
        };

        try {
          const response = await fetch("/web/jobs/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });

          const json = await readJsonResponse(response);
          if (!response.ok) {
            throw new Error(json.detail || "Extraction failed");
          }
          activeJobId = json.job_id;
          setJobControls(true);
          showJobState(json);
          await pollJob(json.job_id);
        } catch (error) {
          handleJobError(error);
        }
      }

      async function cancelExtraction() {
        if (!activeJobId) {
          return;
        }

        cancelButton.disabled = true;
        resultPill.textContent = "running · cancelling";
        resultPill.className = "pill mono";
        summarySelection.innerHTML = "<strong>Job Progress:</strong> waiting for the current step to stop";

        try {
          const response = await fetch(`/web/jobs/${activeJobId}/cancel/`, {
            method: "POST",
          });
          const json = await readJsonResponse(response);
          if (!response.ok) {
            throw new Error(json.detail || "Failed to cancel extraction job.");
          }

          if (json.status === "cancelled") {
            handleCancelledJob(json);
            return;
          }

          showJobState(json);
          setJobControls(true, true);
        } catch (error) {
          handleJobError(error);
        }
      }

      clearButton.addEventListener("click", () => {
        stopPollingJob();
        setJobControls(false);
        ocrDraftInput.value = "";
        hideError();
        renderFields({});
        renderItems([]);
        setJson(metricsView, {});
        setJson(rawView, {});
        resultPill.textContent = "No result yet";
        resultPill.className = "pill mono";
        resetSummary();
      });

      cancelButton.addEventListener("click", cancelExtraction);

      modelFamilySelect.addEventListener("change", () => {
        if (!metaState) {
          return;
        }
        populateModelOptions(metaState, modelFamilySelect.value);
      });

      document.getElementById("extract-form").addEventListener("submit", runExtraction);
      setJobControls(false);
      loadMeta().catch((error) => {
        healthPill.textContent = "metadata error";
        healthPill.className = "pill mono bad";
        showError(error.message);
        setJson(rawView, { error: error.message });
      });
    </script>
  </body>
</html>
"""
