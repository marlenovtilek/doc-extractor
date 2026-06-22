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
        <title>Doc Extractor Pro</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .loader {{ border-top-color: #3498db; animation: spinner 1.5s linear infinite; }}
            @keyframes spinner {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body class="bg-gray-50 font-sans text-[13px] text-gray-800">
        <div class="min-h-screen">
            <nav class="bg-white shadow-sm border-b px-4 py-3">
                <div class="max-w-7xl mx-auto">
                    <h1 class="text-xl font-bold text-gray-800">🤖 Doc Extractor <span class="text-blue-600">Pro</span></h1>
                </div>
            </nav>

            <main class="max-w-7xl mx-auto px-4 py-5">
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-5">
                    <div class="lg:col-span-1 space-y-4">
                        <div class="bg-white p-3 rounded-xl shadow-sm border">
                            <h2 class="text-sm font-semibold mb-2.5 text-gray-700">⚙️ Настройки</h2>
                            
                            <label class="block mb-1 text-xs font-medium">Тип документа</label>
                            <select id="doc_code" class="w-full px-3 py-2 border rounded-lg mb-2.5 text-sm leading-tight"></select>

                            <label class="block mb-1 text-xs font-medium">Провайдер</label>
                            <select id="provider" class="w-full px-3 py-2 border rounded-lg mb-2.5 text-sm leading-tight" onchange="handleProviderChange()"></select>

                            <label class="block mb-1 text-xs font-medium">Модель</label>
                            <select id="model_id" class="w-full px-3 py-2 border rounded-lg mb-2.5 text-sm leading-tight" onchange="handleModelChange()"></select>
                            
                            <label class="block mb-1 text-[11px] font-medium text-gray-400">Custom model string</label>
                            <input type="text" id="custom_model" placeholder="provider::model_id" class="w-full px-3 py-2 border rounded-lg text-sm leading-tight">
                            <p class="mt-1.5 text-[11px] leading-snug text-gray-400">Если поле заполнено, будет использована именно эта модель вместо выбора из списков.</p>
                        </div>

                        <div class="bg-white p-3 rounded-xl shadow-sm border">
                            <label class="block mb-1 text-xs font-medium">Файл документа (для VLM)</label>
                            <input type="file" id="source_file" accept=".pdf,image/*" class="w-full px-3 py-2 bg-gray-50 border rounded-lg text-sm leading-tight mb-2.5">
                            <p class="mb-2.5 text-[11px] leading-snug text-gray-400">Для `vlm::...` загрузи PDF или изображение. Для text-моделей можно оставить только OCR текст.</p>
                            <textarea id="ocr_draft" rows="9" class="w-full px-3 py-2 bg-gray-50 border rounded-lg text-sm leading-snug" placeholder="OCR текст..."></textarea>
                            <button onclick="startExtraction()" id="btn_run" class="w-full mt-2.5 bg-blue-600 text-white font-bold py-2 rounded-lg hover:bg-blue-700 text-sm">
                                ЗАПУСТИТЬ
                            </button>
                        </div>
                    </div>

                    <div class="lg:col-span-2">
                        <div id="result_area" class="bg-white p-3 rounded-xl shadow-sm border min-h-[360px]">
                            <div id="placeholder" class="text-center py-20 text-gray-400 text-sm">Результаты появятся здесь</div>
                            <div id="loading" class="hidden text-center py-20">
                                <div class="loader ease-linear rounded-full border-4 border-t-4 border-gray-200 h-10 w-10 mx-auto mb-3"></div>
                                <p class="text-sm">Обработка...</p>
                            </div>
                            <div id="success_content" class="hidden">
                                <div class="flex justify-between mb-1.5 text-sm">
                                    <span id="stat_count" class="font-bold"></span>
                                    <span id="stat_time" class="text-gray-500"></span>
                                </div>
                                <div class="mb-2.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
                                    <span id="stat_model"></span>
                                    <span id="stat_route"></span>
                                </div>
                                <div class="mb-2.5 space-y-1 text-[11px] text-gray-500">
                                    <div id="stat_scan_helper" class="hidden rounded-md bg-gray-50 px-2 py-1"></div>
                                    <div id="stat_vlm_helper" class="hidden rounded-md bg-gray-50 px-2 py-1"></div>
                                </div>
                                <div id="fields_panel" class="hidden mb-2.5">
                                    <div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Header</div>
                                    <div class="overflow-auto border rounded-lg">
                                        <table class="min-w-full text-[11px] text-left border-collapse">
                                            <thead class="bg-gray-100">
                                                <tr id="fields_header_row"></tr>
                                            </thead>
                                            <tbody>
                                                <tr id="fields_value_row"></tr>
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                                <div id="json_panel" class="hidden mb-2.5">
                                    <pre id="json_payload" class="overflow-auto max-h-[60vh] rounded-lg border bg-gray-50 p-2.5 text-[11px] text-gray-700"></pre>
                                </div>
                                <div id="table_wrapper" class="hidden">
                                    <div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Items</div>
                                    <div class="mb-1.5 text-[11px] text-gray-400">Таблица прокручивается по горизонтали, если колонок много.</div>
                                    <div class="overflow-auto max-h-[72vh] border rounded-lg">
                                        <table class="min-w-full w-max text-[11px] text-left border-collapse">
                                            <thead class="bg-gray-100 sticky top-0 z-10">
                                                <tr id="table_header_row"></tr>
                                            </thead>
                                            <tbody id="table_body"></tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
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
                if (defaultProvider) {{
                    pSelect.value = defaultProvider;
                }}
                updateModels(defaultModelValue);
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

                try {{
                    const formData = new FormData();
                    formData.append('document_code', document.getElementById('doc_code').value);
                    formData.append('ocr_draft', ocr);
                    formData.append('model', finalModel);
                    if (selectedFile) {{
                        formData.append('file', selectedFile);
                    }}

                    const response = await fetch('/web/extract/upload/', {{
                        method: 'POST',
                        body: formData
                    }});
                    const res = await response.json();
                    if (response.ok && res.status === "success") showResults(res);
                    else alert("Ошибка: " + (res.error || res.detail));
                }} catch (e) {{ alert("Сеть: " + e); }}
                finally {{ document.getElementById('loading').classList.add('hidden'); }}
            }}

            function showResults(data) {{
                document.getElementById('success_content').classList.remove('hidden');
                document.getElementById('stat_count').innerText = `Найдено: ${{data.data.count}}`;
                document.getElementById('stat_time').innerText = `Время: ${{data.duration}}s`;
                const execution = (data.metrics && data.metrics.execution) || {{}};
                document.getElementById('stat_model').innerText = data.model_id ? `Модель: ${{data.model_id}}` : '';
                document.getElementById('stat_route').innerText = execution.fallback_used
                    ? `Маршрут: fallback -> ${{execution.final_model || '-' }}`
                    : (execution.final_model ? `Маршрут: primary -> ${{execution.final_model}}` : '');
                renderHelperStat(
                    'stat_scan_helper',
                    'OCR scan-helper',
                    execution.scan_helper_mode,
                    execution.scan_helper_items_count,
                    execution.scan_helper_updates,
                    null
                );
                renderHelperStat(
                    'stat_vlm_helper',
                    'VLM helper',
                    execution.vlm_helper_mode,
                    execution.vlm_helper_items_count,
                    execution.vlm_helper_updates,
                    execution.vlm_helper_model
                );
                
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
                        fieldsHeaderRow.innerHTML += `<th class="px-2 py-1 border border-gray-200 whitespace-nowrap font-semibold">${{escapeHtml(key)}}</th>`;
                        fieldsValueRow.innerHTML += `<td class="px-2 py-1 border border-gray-100 whitespace-nowrap align-top">${{escapeHtml(String(value))}}</td>`;
                    }});
                }}

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
                    items.forEach(item => {{
                        Object.keys(item || {{}}).forEach(key => keySet.add(key));
                    }});
                    const itemKeys = Array.from(keySet);
                    const headerFieldNames = new Set(fieldEntries.map(([key, _]) => key));
                    const keys = [];
                    if (itemKeys.includes('position')) {{
                        keys.push('position');
                    }}
                    itemKeys.forEach(k => {{
                        if (k !== 'position' && !headerFieldNames.has(k)) {{
                            keys.push(k);
                        }}
                    }});
                    keys.forEach(k => thead.innerHTML += `<th class="px-2 py-1 border border-gray-200 whitespace-nowrap font-semibold">${{k}}</th>`);
                    items.forEach(item => {{
                        let row = "<tr>";
                        keys.forEach(k => {{
                            const value = item[k];
                            const display = value === null || value === undefined || value === "" ? "-" : value;
                            row += `<td class="px-2 py-1 border border-gray-100 whitespace-nowrap align-top">${{escapeHtml(String(display))}}</td>`;
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

                if (!mode) {{
                    el.classList.add('hidden');
                    el.textContent = '';
                    return;
                }}

                const parts = [`${{label}}: ${{mode}}`];
                if (modelLabel) {{
                    parts.push(`модель=${{modelLabel}}`);
                }}
                if (itemsCount !== null && itemsCount !== undefined) {{
                    parts.push(`items=${{itemsCount}}`);
                }}
                if (updates !== null && updates !== undefined) {{
                    parts.push(`updates=${{updates}}`);
                }}

                el.textContent = parts.join(' | ');
                el.classList.remove('hidden');
            }}

            window.onload = init;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
