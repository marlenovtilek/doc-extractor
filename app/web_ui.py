import json
from fastapi.responses import HTMLResponse
from extractor.runtime import get_runtime_settings
from extractor.registry import list_document_definitions
from extractor.providers import list_model_families, build_model_spec, resolve_model_target

def render_home_page():
    # Получаем данные
    doc_definitions = list_document_definitions()
    model_families = list_model_families()
    runtime = get_runtime_settings()

    try:
        default_target = resolve_model_target(runtime.llm_model_primary)
        default_provider = default_target.provider
        default_model_value = build_model_spec(default_target.provider, default_target.model_id)
    except Exception:
        first_family = next((family for family in model_families if family.get("models")), {})
        default_provider = first_family.get("provider", "")
        default_model_value = (
            first_family.get("models", [{}])[0].get("value", "")
            if first_family.get("models")
            else ""
        )

    # Сериализуем
    docs_json = json.dumps(doc_definitions, ensure_ascii=False)
    families_json = json.dumps(model_families, ensure_ascii=False)
    default_provider_json = json.dumps(default_provider, ensure_ascii=False)
    default_model_json = json.dumps(default_model_value, ensure_ascii=False)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Doc Extractor Pro</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            * {{ font-family: 'Inter', ui-sans-serif, system-ui, sans-serif; }}
            body {{ background:#f4f5f9; }}
            .loader {{ border-top-color:#4f46e5; animation: spin 1s linear infinite; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
            @keyframes fadeUp {{ from {{ opacity:0; transform: translateY(8px); }} to {{ opacity:1; transform:none; }} }}
            .fade-up {{ animation: fadeUp .35s ease both; }}
            .card {{ background:#fff; border:1px solid #ebedf3; border-radius:16px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
            .nav-item {{ width:44px; height:44px; display:grid; place-items:center; border-radius:14px; color:#9aa1b2; cursor:pointer; transition:.15s; font-size:18px; }}
            .nav-item:hover {{ background:#eef0fb; color:#4f46e5; }}
            .nav-item.active {{ background:linear-gradient(135deg,#4f46e5,#6366f1); color:#fff; box-shadow:0 8px 18px -8px rgba(79,70,229,.6); }}
            ::-webkit-scrollbar {{ height:9px; width:9px; }}
            ::-webkit-scrollbar-thumb {{ background:#d6dae3; border-radius:99px; }}
            ::-webkit-scrollbar-thumb:hover {{ background:#c2c8d4; }}
            .lbl {{ font-size:11px; font-weight:600; letter-spacing:.02em; color:#6b7280; text-transform:uppercase; }}
            select, input[type=text], textarea {{ transition: border-color .15s, box-shadow .15s; }}
            select:focus, input[type=text]:focus, textarea:focus {{ outline:none; border-color:#a5b4fc; box-shadow:0 0 0 3px rgba(99,102,241,.18); }}
            tbody.zebra tr:nth-child(even) {{ background:#fafbff; }}
            tbody.zebra tr:hover {{ background:#eef2ff; }}
        </style>
    </head>
    <body class="text-[13px] text-slate-700">
        <div class="flex min-h-screen">
            <!-- SIDEBAR RAIL -->
            <aside class="hidden md:flex flex-col items-center gap-2 w-[72px] shrink-0 bg-white border-r border-slate-200 py-4 sticky top-0 h-screen">
                <div class="h-11 w-11 rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-500 grid place-items-center text-white text-xl shadow-lg shadow-indigo-300/50 mb-3">📦</div>
                <div class="nav-item active" title="Извлечение">🧾</div>
                <div class="nav-item" title="Результаты">📊</div>
                <div class="nav-item" title="Настройки">⚙️</div>
                <div class="mt-auto nav-item" title="Помощь">❔</div>
            </aside>

            <!-- MAIN -->
            <div class="flex-1 min-w-0">
                <header class="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-white/70 backdrop-blur sticky top-0 z-20">
                    <div>
                        <h1 class="text-[17px] font-extrabold tracking-tight text-slate-800 leading-none">Извлечение инвойса</h1>
                        <p class="text-[11px] text-slate-400 mt-1">VLM-пайплайн · контроль занижения таможенной стоимости</p>
                    </div>
                    <span class="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 px-3 py-1.5 rounded-full bg-slate-100 border border-slate-200">
                        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span> pipeline online
                    </span>
                </header>

                <main class="px-6 py-6">
                  <div class="flex flex-col lg:flex-row gap-5 items-start">
                    <!-- LEFT CONFIG COLUMN -->
                    <section class="card p-5 w-full lg:w-[340px] lg:shrink-0 lg:sticky lg:top-[84px] space-y-4">
                        <h2 class="flex items-center gap-2 text-[13px] font-bold text-slate-800">
                            <span class="text-indigo-500">⚙️</span> Параметры извлечения
                        </h2>

                        <div>
                            <label class="lbl block mb-1">Тип документа</label>
                            <select id="doc_code" class="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm"></select>
                        </div>
                        <div>
                            <label class="lbl block mb-1">Провайдер</label>
                            <select id="provider" class="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm" onchange="handleProviderChange()"></select>
                        </div>
                        <div>
                            <label class="lbl block mb-1">Модель</label>
                            <select id="model_id" class="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm" onchange="handleModelChange()"></select>
                        </div>
                        <div>
                            <label class="lbl block mb-1 text-slate-400">Custom model string</label>
                            <input type="text" id="custom_model" placeholder="provider::model_id" class="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm">
                        </div>

                        <div class="border-t border-slate-100 pt-4">
                            <label class="lbl block mb-1">Файл инвойса (для VLM)</label>
                            <label id="drop_zone" for="source_file" class="group flex flex-col items-center justify-center gap-1.5 w-full px-3 py-6 bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl cursor-pointer hover:border-indigo-300 hover:bg-indigo-50/40 transition">
                                <span class="text-2xl opacity-70 group-hover:scale-110 transition">⬆️</span>
                                <span id="file_name" class="text-[12px] font-medium text-slate-500 text-center">Перетащи или выбери PDF / изображение</span>
                            </label>
                            <input type="file" id="source_file" accept=".pdf,image/*" class="hidden">
                        </div>

                        <div>
                            <label class="lbl block mb-1">OCR текст (опционально)</label>
                            <textarea id="ocr_draft" rows="6" class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-sm leading-snug" placeholder="OCR текст для text-моделей…"></textarea>
                        </div>

                        <button onclick="startExtraction()" id="btn_run" class="group w-full inline-flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-indigo-500 text-white font-bold px-6 py-2.5 rounded-xl shadow-lg shadow-indigo-300/40 hover:shadow-indigo-400/50 hover:-translate-y-px active:translate-y-0 transition text-sm">
                            <span>Запустить извлечение</span>
                            <span class="group-hover:translate-x-0.5 transition">→</span>
                        </button>
                        <p class="text-[11px] text-slate-400">Для <code class="text-indigo-500">vlm::...</code> загрузи PDF/изображение. Если custom-поле заполнено — используется именно оно.</p>
                    </section>

                    <!-- RIGHT RESULTS COLUMN -->
                    <section id="result_area" class="flex-1 min-w-0 w-full">
                        <div id="placeholder" class="card flex flex-col items-center justify-center text-center py-20 text-slate-300">
                            <div class="text-5xl mb-3">🗂️</div>
                            <p class="text-sm font-medium text-slate-400">Результаты появятся здесь</p>
                            <p class="text-[12px] text-slate-300 mt-1">Загрузи инвойс и нажми «Запустить извлечение»</p>
                        </div>

                        <div id="loading" class="hidden card flex flex-col items-center justify-center py-20">
                            <div class="loader rounded-full border-[3px] border-slate-200 h-11 w-11 mb-4"></div>
                            <p class="text-sm font-medium text-slate-500">Обработка страниц…</p>
                            <p class="text-[12px] text-slate-400 mt-1">VLM читает таблицу инвойса</p>
                        </div>

                        <div id="success_content" class="hidden fade-up space-y-5">
                            <!-- metric cards -->
                            <div id="stats_grid" class="grid grid-cols-2 lg:grid-cols-4 gap-4"></div>

                            <!-- validation -->
                            <div id="validation_panel" class="hidden"></div>

                            <!-- helpers -->
                            <div class="space-y-1 text-[11px] text-slate-500">
                                <div id="stat_scan_helper" class="hidden rounded-md bg-slate-50 border border-slate-100 px-2.5 py-1.5"></div>
                                <div id="stat_vlm_helper" class="hidden rounded-md bg-slate-50 border border-slate-100 px-2.5 py-1.5"></div>
                            </div>

                            <!-- header fields -->
                            <div id="fields_panel" class="hidden card p-4">
                                <div class="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">Шапка документа</div>
                                <div class="overflow-auto border border-slate-200 rounded-xl">
                                    <table class="min-w-full text-[11px] text-left border-collapse">
                                        <thead class="bg-slate-50"><tr id="fields_header_row"></tr></thead>
                                        <tbody><tr id="fields_value_row"></tr></tbody>
                                    </table>
                                </div>
                            </div>

                            <!-- json -->
                            <div id="json_panel" class="hidden card p-4">
                                <div class="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">JSON</div>
                                <pre id="json_payload" class="overflow-auto max-h-[60vh] rounded-xl border border-slate-200 bg-slate-900 text-slate-100 p-3 text-[11px] leading-relaxed"></pre>
                            </div>

                            <!-- items -->
                            <div id="table_wrapper" class="hidden card p-4">
                                <div class="flex items-center justify-between mb-2">
                                    <div class="text-[11px] font-bold uppercase tracking-wide text-slate-400">Товарные позиции</div>
                                    <div class="text-[11px] text-slate-400">↔ прокрутка по горизонтали</div>
                                </div>
                                <div class="overflow-auto max-h-[72vh] border border-slate-200 rounded-xl">
                                    <table class="min-w-full w-max text-[11px] text-left border-collapse">
                                        <thead class="bg-slate-100 sticky top-0 z-10"><tr id="table_header_row"></tr></thead>
                                        <tbody id="table_body" class="zebra"></tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </section>
                  </div>
                </main>
            </div>
        </div>

        <script>
            const docDefinitions = {docs_json};
            const modelFamilies = {families_json};
            const defaultProvider = {default_provider_json};
            const defaultModelValue = {default_model_json};

            function init() {{
                const dSelect = document.getElementById('doc_code');
                docDefinitions.forEach(doc => {{
                    const opt = document.createElement('option');
                    opt.value = doc.document_code;
                    opt.innerText = `${{doc.document_code}} (${{doc.label}})`;
                    dSelect.appendChild(opt);
                }});

                const pSelect = document.getElementById('provider');
                modelFamilies.forEach(fam => {{
                    const opt = document.createElement('option');
                    opt.value = fam.provider;
                    opt.innerText = fam.label + (fam.configured ? "" : " (не настроен)");
                    pSelect.appendChild(opt);
                }});
                if (defaultProvider) {{ pSelect.value = defaultProvider; }}
                updateModels(defaultModelValue);

                const fileInput = document.getElementById('source_file');
                fileInput.addEventListener('change', () => {{
                    const f = fileInput.files[0];
                    document.getElementById('file_name').innerText = f ? f.name : 'Перетащи или выбери PDF / изображение';
                }});
                const dz = document.getElementById('drop_zone');
                ['dragover','dragenter'].forEach(ev => dz.addEventListener(ev, e => {{
                    e.preventDefault(); dz.classList.add('border-indigo-400','bg-indigo-50/60');
                }}));
                ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => {{
                    e.preventDefault(); dz.classList.remove('border-indigo-400','bg-indigo-50/60');
                }}));
                dz.addEventListener('drop', e => {{
                    if (e.dataTransfer.files.length) {{
                        fileInput.files = e.dataTransfer.files;
                        fileInput.dispatchEvent(new Event('change'));
                    }}
                }});
            }}

            function getSelectedDocDefinition() {{
                const selectedCode = document.getElementById('doc_code').value;
                return docDefinitions.find(doc => doc.document_code === selectedCode) || null;
            }}

            function updateModels(preferredValue = "") {{
                const pValue = document.getElementById('provider').value;
                const mSelect = document.getElementById('model_id');
                mSelect.innerHTML = "";
                const family = modelFamilies.find(f => f.provider === pValue);
                if (family) {{
                    family.models.forEach(m => {{
                        const opt = document.createElement('option');
                        opt.value = m.value;
                        opt.innerText = m.label;
                        mSelect.appendChild(opt);
                    }});
                    if (preferredValue && family.models.some(m => m.value === preferredValue)) {{
                        mSelect.value = preferredValue;
                    }}
                }}
            }}

            function handleProviderChange() {{
                updateModels();
                document.getElementById('custom_model').value = "";
            }}

            function handleModelChange() {{
                document.getElementById('custom_model').value = "";
            }}

            async function startExtraction() {{
                const ocr = document.getElementById('ocr_draft').value;
                const custom = document.getElementById('custom_model').value;
                const finalModel = custom || document.getElementById('model_id').value;
                const selectedFile = document.getElementById('source_file').files[0] || null;
                const isVlm = finalModel.startsWith('vlm::') || document.getElementById('provider').value === 'vlm';
                if (!ocr.trim() && !isVlm) return alert("Нет текста!");
                if (isVlm && !selectedFile) return alert("Для VLM нужно выбрать PDF или изображение.");

                document.getElementById('placeholder').classList.add('hidden');
                document.getElementById('success_content').classList.add('hidden');
                document.getElementById('loading').classList.remove('hidden');
                const btn = document.getElementById('btn_run');
                btn.disabled = true; btn.classList.add('opacity-60','pointer-events-none');

                try {{
                    const formData = new FormData();
                    formData.append('document_code', document.getElementById('doc_code').value);
                    formData.append('ocr_draft', ocr);
                    formData.append('model', finalModel);
                    if (selectedFile) {{ formData.append('file', selectedFile); }}

                    const response = await fetch('/web/extract/upload/', {{ method: 'POST', body: formData }});
                    const res = await response.json();
                    if (response.ok && res.status === "success") showResults(res);
                    else alert("Ошибка: " + (res.error || res.detail));
                }} catch (e) {{ alert("Сеть: " + e); }}
                finally {{
                    document.getElementById('loading').classList.add('hidden');
                    btn.disabled = false; btn.classList.remove('opacity-60','pointer-events-none');
                }}
            }}

            function chip(label, value, accent) {{
                const tones = {{
                    indigo: 'text-indigo-600',
                    cyan:   'text-cyan-600',
                    slate:  'text-slate-700',
                    amber:  'text-amber-600',
                }};
                const tone = tones[accent] || tones.slate;
                return `<div class="card p-4">
                    <div class="lbl mb-1">${{escapeHtml(label)}}</div>
                    <div class="text-[20px] font-extrabold leading-tight ${{tone}} truncate" title="${{escapeHtml(String(value))}}">${{escapeHtml(String(value))}}</div>
                </div>`;
            }}

            const REASON_LABELS = {{
                sum_exceeds_total: 'Сумма строк превышает итог инвойса',
                sum_below_total: 'Сумма строк меньше итога — возможна потеря строк',
                count_vs_max_line_mismatch: 'Число строк ≠ макс. номеру позиции',
                sum_off_total_minor: 'Небольшое расхождение суммы с итогом',
                row_arithmetic_anomalies: 'Есть строки, где кол-во × цена ≠ сумма',
            }};

            function fmtNum(v) {{
                if (v === null || v === undefined || v === "") return '—';
                const n = Number(v);
                if (!isFinite(n)) return String(v);
                return n.toLocaleString('ru-RU', {{ maximumFractionDigits: 2 }});
            }}

            function renderValidation(val) {{
                const panel = document.getElementById('validation_panel');
                if (!val) {{ panel.classList.add('hidden'); panel.innerHTML = ''; return; }}

                const reasons = val.review_reasons || [];
                const warnings = val.warnings || [];
                let tone, title, icon;
                if (val.review_needed) {{
                    tone = {{ bg:'bg-rose-50', bd:'border-rose-200', tx:'text-rose-700', badge:'bg-rose-100 text-rose-700', dot:'bg-rose-500' }};
                    title = 'Требуется проверка'; icon = '⚠️';
                }} else if (warnings.length) {{
                    tone = {{ bg:'bg-amber-50', bd:'border-amber-200', tx:'text-amber-800', badge:'bg-amber-100 text-amber-800', dot:'bg-amber-500' }};
                    title = 'Предупреждения'; icon = '🔎';
                }} else if (val.stated_total) {{
                    tone = {{ bg:'bg-emerald-50', bd:'border-emerald-200', tx:'text-emerald-700', badge:'bg-emerald-100 text-emerald-700', dot:'bg-emerald-500' }};
                    title = 'Сходится с итогом инвойса'; icon = '✅';
                }} else {{
                    tone = {{ bg:'bg-slate-50', bd:'border-slate-200', tx:'text-slate-600', badge:'bg-slate-100 text-slate-600', dot:'bg-slate-400' }};
                    title = 'Нет суммы инвойса для сверки'; icon = 'ℹ️';
                }}

                const ratioPct = (val.sum_to_total_ratio !== null && val.sum_to_total_ratio !== undefined)
                    ? Math.round(val.sum_to_total_ratio * 100) + '%' : '—';
                const flags = [...reasons, ...warnings]
                    .map(c => `<span class="inline-flex items-center gap-1 ${{tone.badge}} rounded-full px-2 py-0.5 text-[11px] font-medium">${{escapeHtml(REASON_LABELS[c] || c)}}</span>`)
                    .join('');

                const anomalies = val.row_anomalies || [];
                let anomaliesHtml = '';
                if (anomalies.length) {{
                    const rows = anomalies.slice(0, 12).map(a =>
                        `<tr class="border-t border-slate-100">
                            <td class="px-2 py-1 font-semibold">#${{a.position}}</td>
                            <td class="px-2 py-1">${{escapeHtml(String(a.quantity ?? '—'))}}</td>
                            <td class="px-2 py-1">${{escapeHtml(String(a.price ?? '—'))}}</td>
                            <td class="px-2 py-1 text-rose-600 font-medium">${{escapeHtml(String(a.cost ?? '—'))}}</td>
                            <td class="px-2 py-1 text-emerald-600">${{fmtNum(a.expected_cost)}}</td>
                        </tr>`).join('');
                    const more = anomalies.length > 12 ? `<div class="text-[11px] text-slate-400 mt-1">…ещё ${{anomalies.length - 12}}</div>` : '';
                    anomaliesHtml = `
                        <div class="mt-3">
                            <div class="text-[11px] font-semibold ${{tone.tx}} mb-1">Подозрительные строки (кол-во × цена ≠ сумма)</div>
                            <div class="overflow-auto rounded-lg border border-slate-200 bg-white">
                                <table class="min-w-full text-[11px] text-left">
                                    <thead class="bg-slate-50 text-slate-500">
                                        <tr><th class="px-2 py-1">Поз.</th><th class="px-2 py-1">Кол-во</th><th class="px-2 py-1">Цена</th><th class="px-2 py-1">Сумма (инвойс)</th><th class="px-2 py-1">Ожидалось</th></tr>
                                    </thead>
                                    <tbody>${{rows}}</tbody>
                                </table>
                            </div>${{more}}
                        </div>`;
                }}

                panel.className = `${{tone.bg}} ${{tone.bd}} border rounded-2xl p-4`;
                panel.innerHTML = `
                    <div class="flex items-start gap-2.5">
                        <span class="text-lg leading-none mt-0.5">${{icon}}</span>
                        <div class="flex-1">
                            <div class="flex items-center gap-2">
                                <span class="inline-block h-2 w-2 rounded-full ${{tone.dot}}"></span>
                                <span class="text-[13px] font-bold ${{tone.tx}}">${{title}}</span>
                            </div>
                            <div class="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-[12px]">
                                <div><span class="text-slate-400">Итог инвойса:</span> <b>${{fmtNum(val.stated_total)}}</b></div>
                                <div><span class="text-slate-400">Сумма строк:</span> <b>${{fmtNum(val.sum_cost)}}</b></div>
                                <div><span class="text-slate-400">Совпадение:</span> <b>${{ratioPct}}</b></div>
                                <div><span class="text-slate-400">Строк / макс.№:</span> <b>${{val.count ?? '—'}} / ${{val.max_line_no ?? '—'}}</b></div>
                            </div>
                            ${{flags ? `<div class="mt-2.5 flex flex-wrap gap-1.5">${{flags}}</div>` : ''}}
                            ${{anomaliesHtml}}
                        </div>
                    </div>`;
                panel.classList.remove('hidden');
            }}

            function showResults(data) {{
                document.getElementById('success_content').classList.remove('hidden');

                const execution = (data.metrics && data.metrics.execution) || {{}};
                const validation = (data.metrics && data.metrics.validation) || null;
                const routeText = execution.fallback_used
                    ? `fallback → ${{execution.final_model || '-'}}`
                    : (execution.final_model ? `${{execution.final_model}}` : '—');

                document.getElementById('stats_grid').innerHTML = [
                    chip('Найдено позиций', data.data.count ?? 0, 'indigo'),
                    chip('Время', (data.duration ?? 0) + ' c', 'cyan'),
                    chip('Модель', data.model_id || '—', 'slate'),
                    chip('Маршрут', routeText, execution.fallback_used ? 'amber' : 'slate'),
                ].join('');

                renderValidation(validation);

                renderHelperStat('stat_scan_helper', 'OCR scan-helper', execution.scan_helper_mode,
                    execution.scan_helper_items_count, execution.scan_helper_updates, null);
                renderHelperStat('stat_vlm_helper', 'VLM helper', execution.vlm_helper_mode,
                    execution.vlm_helper_items_count, execution.vlm_helper_updates, execution.vlm_helper_model);

                const tbody = document.getElementById('table_body');
                const thead = document.getElementById('table_header_row');
                const fieldsPanel = document.getElementById('fields_panel');
                const fieldsHeaderRow = document.getElementById('fields_header_row');
                const fieldsValueRow = document.getElementById('fields_value_row');
                const jsonPanel = document.getElementById('json_panel');
                const jsonPayload = document.getElementById('json_payload');
                const tableWrapper = document.getElementById('table_wrapper');
                tbody.innerHTML = ""; thead.innerHTML = "";
                fieldsHeaderRow.innerHTML = "";
                fieldsValueRow.innerHTML = "";
                fieldsPanel.classList.add('hidden');
                jsonPanel.classList.add('hidden');
                jsonPayload.textContent = "";
                tableWrapper.classList.add('hidden');

                const resultType = data.result_type || "";
                const fields = (data.data && data.data.fields) || {{}};
                const items = data.data.items || [];
                const selectedDoc = getSelectedDocDefinition();
                const schemaFieldKeys = ((selectedDoc && selectedDoc.schema && selectedDoc.schema.fields) || [])
                    .map(field => field.name)
                    .filter(Boolean);
                const fieldKeySet = new Set(schemaFieldKeys);
                Object.keys(fields).forEach(key => fieldKeySet.add(key));
                const fieldEntries = Array.from(fieldKeySet).map(key => {{
                    const value = fields[key];
                    const display = value === null || value === undefined || value === "" ? "-" : value;
                    return [key, display];
                }});

                if (fieldEntries.length > 0) {{
                    fieldsPanel.classList.remove('hidden');
                    fieldEntries.forEach(([key, value]) => {{
                        fieldsHeaderRow.innerHTML += `<th class="px-2.5 py-1.5 border-b border-slate-200 whitespace-nowrap font-bold text-slate-500 uppercase text-[10px] tracking-wide">${{escapeHtml(key)}}</th>`;
                        fieldsValueRow.innerHTML += `<td class="px-2.5 py-1.5 border-b border-slate-100 whitespace-nowrap align-top font-medium text-slate-700">${{escapeHtml(String(value))}}</td>`;
                    }});
                }}

                const anomalyPositions = new Set(((validation && validation.row_anomalies) || []).map(a => a.position));

                if (resultType === 'object') {{
                    jsonPanel.classList.remove('hidden');
                    jsonPayload.textContent = JSON.stringify(data.data, null, 2);
                }} else if (items.length > 0) {{
                    tableWrapper.classList.remove('hidden');
                    const schemaKeys = ((selectedDoc && selectedDoc.schema && selectedDoc.schema.item_fields) || [])
                        .map(field => field.name)
                        .filter(Boolean);
                    const keySet = new Set();
                    schemaKeys.forEach(key => keySet.add(key));
                    items.forEach(item => {{ Object.keys(item || {{}}).forEach(key => keySet.add(key)); }});
                    const itemKeys = Array.from(keySet);
                    const headerFieldNames = new Set(fieldEntries.map(([key, _]) => key));
                    const keys = [];
                    if (itemKeys.includes('position')) {{ keys.push('position'); }}
                    itemKeys.forEach(k => {{
                        if (k !== 'position' && !headerFieldNames.has(k)) {{ keys.push(k); }}
                    }});
                    thead.innerHTML += `<th class="px-2.5 py-2 border-b border-slate-200 whitespace-nowrap font-bold text-slate-500 uppercase text-[10px] tracking-wide">#</th>`;
                    keys.forEach(k => thead.innerHTML += `<th class="px-2.5 py-2 border-b border-slate-200 whitespace-nowrap font-bold text-slate-500 uppercase text-[10px] tracking-wide">${{escapeHtml(k)}}</th>`);
                    items.forEach((item, i) => {{
                        const pos = i + 1;
                        const flagged = anomalyPositions.has(pos);
                        let row = `<tr class="${{flagged ? 'bg-rose-50/70' : ''}}">`;
                        row += `<td class="px-2.5 py-1.5 border-b border-slate-100 text-slate-400 font-mono">${{flagged ? '⚠ ' : ''}}${{pos}}</td>`;
                        keys.forEach(k => {{
                            const value = item[k];
                            const display = value === null || value === undefined || value === "" ? "-" : value;
                            row += `<td class="px-2.5 py-1.5 border-b border-slate-100 whitespace-nowrap align-top">${{escapeHtml(String(display))}}</td>`;
                        }});
                        tbody.innerHTML += row + "</tr>";
                    }});
                }}
            }}

            function escapeHtml(value) {{
                return value
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#39;');
            }}

            function renderHelperStat(elementId, label, mode, itemsCount, updates, modelLabel) {{
                const el = document.getElementById(elementId);
                if (!el) return;
                if (!mode) {{ el.classList.add('hidden'); el.textContent = ''; return; }}
                const parts = [`${{label}}: ${{mode}}`];
                if (modelLabel) {{ parts.push(`модель=${{modelLabel}}`); }}
                if (itemsCount !== null && itemsCount !== undefined) {{ parts.push(`items=${{itemsCount}}`); }}
                if (updates !== null && updates !== undefined) {{ parts.push(`updates=${{updates}}`); }}
                el.textContent = parts.join(' · ');
                el.classList.remove('hidden');
            }}

            window.onload = init;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
