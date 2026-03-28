# Архитектура проекта

Этот файл объясняет, как устроен `doc-extractor` внутри.

Это не инструкция по запуску и не `README`.
Его задача — помочь разработчику быстро понять:
- что делает сервис
- как запрос проходит через систему
- где живет логика invoice
- где живет логика обычных документов
- какие файлы читать в первую очередь


## 1. Что это за сервис

`doc-extractor` — это stateless-сервис для извлечения структуры из OCR-текста.

На вход он получает:
- `document_code`
- `ocr_draft`
- необязательный `model`

На выходе отдает:
- структурированные поля
- структурированные строки таблиц для табличных документов
- метрики
- описание ошибки, если извлечение не удалось

Сервис не хранит бизнес-данные документов в базе.
Он принимает запрос, обрабатывает его и сразу возвращает ответ.

В проекте также есть встроенный web UI для локальной работы и отладки, но основное назначение проекта — extraction API.


## 2. Общий поток запроса

```text
Клиент
  ->
FastAPI endpoint
  ->
execute_extraction_request(...)
  ->
registry находит нужный handler
  ->
выбирается модель
  ->
handler.extract(...)
  ->
документ-специфичный pipeline
  ->
нормализованный ответ
  ->
клиент
```

Главная цепочка в коде выглядит так:

```text
app/main.py
  ->
extractor/services/extraction.py
  ->
extractor/documents/registry.py
  ->
конкретный handler
```


## 3. Какие файлы читать сначала

Если человек впервые открыл проект, лучше идти в таком порядке:

1. [`app/main.py`](./app/main.py)
   Здесь находится HTTP-слой и публичные endpoints.

2. [`extractor/services/extraction.py`](./extractor/services/extraction.py)
   Центральный роутер extraction-запроса.

3. [`extractor/documents/registry.py`](./extractor/documents/registry.py)
   Таблица соответствия `document_code -> handler`.

4. [`extractor/documents/base.py`](./extractor/documents/base.py)
   Общие контракты: schema, handler, definition.

5. Потом выбрать одну из двух веток:
   - invoice flow: [`extractor/documents/invoice/invoice.py`](./extractor/documents/invoice/invoice.py)
   - обычные object-документы: [`extractor/documents/object_core.py`](./extractor/documents/object_core.py)


## 4. HTTP-слой

Файл:
- [`app/main.py`](./app/main.py)

Этот файл определяет:
- `/api/health/`
- `/api/meta/`
- `/api/extract/`
- `/web/*` endpoints для встроенного интерфейса и фоновых job’ов

Важно:
- обработчики в `app/main.py` объявлены как `async def`
- но внутренняя бизнес-логика в основном остается обычным синхронным Python-кодом

То есть проект асинхронный на уровне HTTP, но сам pipeline извлечения не является полностью асинхронным pipeline.


## 5. Центральный роутер извлечения

Файл:
- [`extractor/services/extraction.py`](./extractor/services/extraction.py)

Это основной диспетчер extraction-запросов.

Он делает пять ключевых вещей:

1. Находит определение документа по `document_code`
2. Решает, какую модель использовать
3. Вызывает handler нужного документа
4. Объединяет результат handler’а со schema и metrics
5. Возвращает единый формат ответа

Главная функция:
- `execute_extraction_request(...)`

Это главный вход в extraction-логику после HTTP-слоя.


## 6. Реестр документов

Файл:
- [`extractor/documents/registry.py`](./extractor/documents/registry.py)

Registry — это таблица всех поддерживаемых типов документов.

Он строит `DocumentDefinition` для каждого handler’а:

```text
document_code -> label -> handler -> schema
```

Именно registry говорит сервису:
- какой handler запускать
- является документ `table` или `object`
- какие поля у этого документа должны быть в ответе


## 7. Общий контракт документов

Файл:
- [`extractor/documents/base.py`](./extractor/documents/base.py)

Основные абстракции:

- `DocumentFieldSchema`
  описание одного поля результата

- `DocumentSchema`
  полный контракт документа

- `DocumentDefinition`
  связывает код документа, название, schema и handler

- `DocumentHandler`
  базовый абстрактный класс с:
  - `document_code`
  - `label`
  - `schema`
  - `extract(...)`

Это общий фундамент, который удерживает все document handlers в одном формате.


## 8. Две основные семьи обработки

В проекте есть два больших типа extraction-flow.

### A. Табличная обработка invoice-стиля

Используется для:
- invoice
- technical document
- protocol-подобных табличных документов

Эта ветка более эвристическая и parser-heavy.

### B. Object-style обработка

Используется для:
- contract
- power of attorney
- supply contract
- passport
- certificate-подобных документов
- других не табличных документов

Эта ветка проще и сильнее опирается на извлечение полей.


## 9. Поток обычных object-документов

Главный файл:
- [`extractor/documents/object_core.py`](./extractor/documents/object_core.py)

Большинство обычных документов используют общий pipeline.

Поток выглядит так:

```text
OCR text
  ->
clean_object_text(...)
  ->
LLM entity extraction
  ->
aggregate_object_fields(...)
  ->
validate_object_fields(...)
  ->
нормализованный object response
```

Главная общая функция:
- `run_object_document_extraction(...)`

Большинство regular handlers очень тонкие.
Обычно handler только объявляет:
- prompt
- examples
- tracked fields
- schema

А сам flow наследует через:
- `ConfiguredObjectHandler`

Поэтому многие regular document files короткие и читаются легко.


## 10. Поток invoice

Главные файлы:
- [`extractor/documents/invoice/invoice.py`](./extractor/documents/invoice/invoice.py)
- [`extractor/documents/invoice/invoice_pipeline.py`](./extractor/documents/invoice/invoice_pipeline.py)

Invoice — самая специализированная часть проекта.
У него отдельный pipeline, потому что OCR таблиц часто очень шумный и требует нескольких стадий ремонта.

### Invoice flow в общем виде

```text
OCR draft
  ->
clean_text(...)
  ->
build_header_metadata(...)
  ->
extract_structured_pipe_items(...)
  ->
оценка качества structured parser
  ->
выбор:
    parser-first
    или llm-first
  ->
normalize / deduplicate / recover
  ->
финальный invoice result
```

### Главное решение в invoice pipeline

Pipeline сначала пытается вытащить структуру напрямую из OCR.

Потом оценивает, насколько этот parser result хороший.

Если parser result достаточно сильный:
- используется parser-first
- при необходимости включается selective line-level assist только для проблемных строк

Если parser result слабый:
- запускается полный LLM path
- результат валидируется и нормализуется

Это решение принимается в:
- [`extractor/documents/invoice/invoice_pipeline.py`](./extractor/documents/invoice/invoice_pipeline.py)


## 11. Модули invoice и их ответственность

Invoice-код разделен по зонам ответственности.

### [`invoice.py`](./extractor/documents/invoice/invoice.py)

Это публичный handler-слой.

Он:
- определяет schema invoice
- экспортирует `InvoiceHandler`
- собирает верхнеуровневые поля ответа
- строит `review_summary` и `top_review_items`
- связывает pipeline с registry

### [`invoice_pipeline.py`](./extractor/documents/invoice/invoice_pipeline.py)

Это orchestration-слой.

Он:
- запускает invoice flow в правильном порядке
- выбирает parser-first или llm-first
- выполняет merge после selective assist
- собирает финальный extraction result

### [`invoice_cleaner.py`](./extractor/documents/invoice/invoice_cleaner.py)

Это слой очистки OCR.

Он:
- чистит шумный OCR
- восстанавливает сплющенные OCR-блоки
- ремонтирует broken table-like text
- подготавливает текст для downstream parsing

### [`invoice_parser.py`](./extractor/documents/invoice/invoice_parser.py)
### [`invoice_parser_extractors.py`](./extractor/documents/invoice/invoice_parser_extractors.py)
### [`invoice_parser_assessment.py`](./extractor/documents/invoice/invoice_parser_assessment.py)

Эти файлы отвечают за извлечение строк таблицы.

Они:
- находят candidate rows
- парсят колонки из OCR-heavy текста
- оценивают, достаточно ли хорош parser result
- собирают unresolved lines для selective repair

### [`invoice_postprocess.py`](./extractor/documents/invoice/invoice_postprocess.py)
и его helper-модули

Это слой нормализации и ремонта результата.

Он:
- подставляет поля из header metadata
- удаляет дубликаты
- убирает OCR shadow rows
- выравнивает peer-строки
- добавляет review metadata

### [`invoice_assist.py`](./extractor/documents/invoice/invoice_assist.py)

Это слой selective repair.

Он используется, когда parser-first уже дал хороший результат, но несколько строк все еще нужно починить.

Вместо повторного запуска всего invoice через тяжелый model path, он ремонтирует только проблемные строки.


## 12. Parser-first против LLM-first

Самая важная идея в этом проекте:

```text
Не отправлять весь invoice в LLM, если parser уже справился достаточно хорошо.
```

Почему это важно:
- быстрее
- дешевле
- легче контролировать
- часто стабильнее на шумном tabular OCR

Поэтому invoice pipeline сначала пробует:

```text
structured parser
  ->
quality assessment
  ->
parser-first если возможно
  ->
selective assist только если нужно
```

Полный LLM path остается как fallback, если качество parser result недостаточно.


## 13. Форма ответа

Сервис возвращает один общий формат ответа для всех документов.

Верхний уровень:

```text
status
document_code
result_type
document_schema
data
model_id
items
count
metrics
error
```

Для object-документов:
- `data.fields` — основной полезный payload
- `data.items` обычно пустой

Для table-документов:
- `data.items` — основной полезный payload
- `data.fields` содержит верхнеуровневую metadata, если она есть

Для invoice дополнительно могут появляться:
- `review_summary`
- `top_review_items`

Это вспомогательные поля для интерфейсов ручной проверки.


## 14. Выбор модели

Логика выбора модели находится в:
- [`extractor/services/extraction.py`](./extractor/services/extraction.py)

Сервис может:
- использовать модель, явно переданную в запросе
- или auto-route модель по типу документа и форме OCR

Сигналы, которые учитываются:
- result type
- длина OCR
- количество pipe-like строк
- количество HTML table tags

Это позволяет выбирать более подходящую модель для:
- больших табличных OCR
- небольших object-документов
- fallback-сценариев


## 15. Метрики и наблюдаемость

Во время extraction собираются метрики и возвращаются в ответе.

Например:
- время очистки
- время валидации
- время финализации
- общее время
- token usage
- field fill rates
- execution path

Invoice-метрики особенно полезны, потому что показывают:
- был ли использован parser-first
- включался ли assist
- использовался ли fallback


## 16. Web UI и web jobs

В проекте есть локальный/operator web UI:
- [`app/web_ui.py`](./app/web_ui.py)

Он умеет:
- отправлять extraction-запросы
- показывать fields и rows
- отображать статус моделей и провайдеров
- показывать review queue для invoice

Также есть небольшой сервис web jobs:
- [`extractor/services/jobs.py`](./extractor/services/jobs.py)

Важно:
- это только in-memory runtime state
- это не persistent business-data store
- это полезно для встроенного web UI, но не является основным extraction-контрактом


## 17. Асинхронность и параллельность

Это важно понимать перед продакшен-использованием.

### Что здесь асинхронное

- FastAPI route handlers объявлены как `async def`
- HTTP-слой может принимать несколько запросов

### Что не является полностью async

- большая часть extraction-логики — обычный Python-код
- parsing и normalization синхронные
- provider calls не построены как полный async pipeline через весь проект

Практическая модель сейчас такая:

```text
async HTTP вход
  +
синхронная extraction-работа
  +
конкурентность за счет server workers / threads
```

То есть сервис может обрабатывать несколько запросов, но реальная пропускная способность все равно зависит от:
- количества server workers
- latency провайдеров
- размера документа
- стоимости invoice parsing


## 18. Как читать код по задачам

### Если нужно понять API

Читать:
- [`app/main.py`](./app/main.py)
- [`extractor/services/extraction.py`](./extractor/services/extraction.py)

### Если нужно добавить новый regular object document

Читать:
- [`extractor/documents/object_core.py`](./extractor/documents/object_core.py)
- один простой handler, например [`extractor/documents/regular/contract.py`](./extractor/documents/regular/contract.py)
- [`extractor/documents/registry.py`](./extractor/documents/registry.py)

### Если нужно улучшать качество invoice

Читать:
- [`extractor/documents/invoice/invoice_pipeline.py`](./extractor/documents/invoice/invoice_pipeline.py)
- [`extractor/documents/invoice/invoice_cleaner.py`](./extractor/documents/invoice/invoice_cleaner.py)
- [`extractor/documents/invoice/invoice_parser.py`](./extractor/documents/invoice/invoice_parser.py)
- [`extractor/documents/invoice/invoice_parser_extractors.py`](./extractor/documents/invoice/invoice_parser_extractors.py)
- [`extractor/documents/invoice/invoice_postprocess.py`](./extractor/documents/invoice/invoice_postprocess.py)

### Если нужно отлаживать model selection

Читать:
- [`extractor/services/extraction.py`](./extractor/services/extraction.py)
- [`extractor/integrations/providers.py`](./extractor/integrations/providers.py)
- [`extractor/config/runtime.py`](./extractor/config/runtime.py)


## 19. Ментальная схема проекта

```text
                +----------------------+
                |      app/main.py     |
                |   FastAPI endpoints  |
                +----------+-----------+
                           |
                           v
                +----------------------+
                | services/extraction  |
                | route + model select |
                +----------+-----------+
                           |
                           v
                +----------------------+
                | documents/registry   |
                | code -> handler      |
                +----------+-----------+
                           |
          +----------------+----------------+
          |                                 |
          v                                 v
+------------------------+      +-------------------------+
| invoice family         |      | object document family  |
| cleaner -> parser ->   |      | clean -> extract ->     |
| assess -> assist ->    |      | aggregate -> validate   |
| postprocess            |      |                         |
+-----------+------------+      +------------+------------+
            |                                |
            +----------------+---------------+
                             |
                             v
                  +------------------------+
                  | normalized API result  |
                  +------------------------+
```


## 20. Краткий итог

Если запомнить только пять вещей про этот проект, то вот они:

1. `app/main.py` — это только HTTP-оболочка.
2. `services/extraction.py` — главный диспетчер extraction-запроса.
3. `registry.py` решает, какой handler будет запущен.
4. Большинство обычных документов используют общий object pipeline.
5. Invoice — особый случай с parser-first workflow и несколькими стадиями ремонта OCR.
