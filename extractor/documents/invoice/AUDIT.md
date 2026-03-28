# Invoice Module Audit

Date: 2026-03-27

## Goal

Reduce responsibility overlap in the invoice package and keep orchestration,
parsing, normalization, and technical-document handling separated.

## Hotspots Found

Before refactor, the main hotspots were:

1. `invoice.py`
   - Mixed invoice workflow, technical-document workflow, handler classes, LLM
     execution, and response shaping in one file.

2. `invoice_parser.py`
   - Mixed parsing strategies, candidate-row assessment, line-repair candidate
     discovery, and a very large `extract_structured_pipe_items()` loop.

3. `invoice_postprocess.py`
   - Was mixing deduplication, country cleanup, peer enrichment, shadow-row
     pruning, and normalization in one file.

4. `invoice_cleaner.py`
   - Was mixing OCR rehydration, pipe-table normalization, cell heuristics, and
     compacting logic in one file.

## Changes Applied

### 1. Invoice orchestration extracted

New module:

- `invoice_pipeline.py`

Responsibility:

- clean OCR text
- build header metadata
- run parser-first path
- run selective assist path
- run LLM primary/fallback path
- finalize normalized invoice items

`invoice.py` is now a thin facade that:

- keeps public entry points stable
- keeps test patch points stable
- owns only handler wiring and dependency injection into the workflow

### 2. Technical-document workflow extracted and moved out of invoice

New module:

- `extractor/documents/regular/technical_document.py`

Responsibility:

- technical-document OCR cleanup
- technical-document normalization helpers
- technical-document extraction workflow

Compatibility is kept through thin wrappers in `invoice.py`:

- `clean_technical_document_text()`
- `run_technical_document_extraction()`
- `TechnicalDocumentHandler`

### 3. Parser assessment extracted

New module:

- `invoice_parser_assessment.py`

Responsibility:

- candidate-row counting
- unique-row counting
- parser completeness assessment
- unresolved line collection for selective assist

This keeps `invoice_parser.py` focused on row parsing instead of parser scoring.

### 4. Main parser loop simplified

`extract_structured_pipe_items()` was decomposed into smaller steps:

- `_merge_split_candidate_line()`
- `_try_promote_positionless_companion()`
- `_normalize_positioned_cells()`
- `_extract_loose_hs_tail_item()`
- `_extract_line_item()`

This keeps the top-level parser loop much easier to read and reason about.

### 5. Parser strategies and support extracted

New modules:

- `invoice_parser_support.py`
- `invoice_parser_extractors.py`

Responsibilities:

- `invoice_parser_support.py`
  - country token normalization
  - quantity / cost / price heuristics
  - description and declaration helpers
  - line-signature building
  - country-origin normalization helpers
  - shared position parsing helpers

- `invoice_parser_extractors.py`
  - HS-last extraction
  - sparse HS extraction without country
  - compact no-HS extraction
  - shifted-tail extraction
  - partial companion extraction
  - loose HS-tail extraction
  - parser strategy composition

`invoice_parser.py` is now a thin row-level orchestrator that:

- merges split OCR rows
- normalizes positioned rows
- promotes positionless companions
- delegates actual item parsing to extractor strategies
- preserves the old public imports used by tests and handlers

### 6. Postprocess split by responsibility

New modules:

- `invoice_postprocess_country.py`
- `invoice_postprocess_dedup.py`
- `invoice_postprocess_peer.py`

Responsibilities:

- `invoice_postprocess_country.py`
  - country cleanup
  - derived field filling
  - numeric reconciliation

- `invoice_postprocess_dedup.py`
  - OCR anomaly filtering
  - deduplication
  - final position sorting

- `invoice_postprocess_peer.py`
  - peer enrichment
  - position-group harmonization
  - shadow-row pruning

`invoice_postprocess.py` is now a thin orchestrator that preserves old public
imports and composes these stages.

### 7. Cleaner split by responsibility

New modules:

- `invoice_cleaner_rehydrate.py`
- `invoice_cleaner_pipe.py`
- `invoice_cleaner_compact.py`

Responsibilities:

- `invoice_cleaner_rehydrate.py`
  - coarse OCR blob rehydration into line structure

- `invoice_cleaner_pipe.py`
  - pipe-table normalization
  - markup stripping

- `invoice_cleaner_compact.py`
  - row compaction
  - schema normalization
  - blob-noise filtering helpers

`invoice_cleaner.py` now serves as a facade for the cleaner pipeline while
keeping base predicates and helper functions used by the parser.

## Current Package Boundaries

- `invoice.py`
  - public invoice facade
  - test-compatible wrappers
  - handler classes

- `invoice_pipeline.py`
  - invoice workflow orchestration

- `invoice_cleaner.py`
  - cleaner facade plus shared low-level heuristics
- `invoice_cleaner_rehydrate.py`
  - OCR blob rehydration
- `invoice_cleaner_pipe.py`
  - pipe normalization and markup stripping
- `invoice_cleaner_compact.py`
  - row compaction and schema cleanup

- `invoice_parser.py`
  - row-level parser orchestration
- `invoice_parser_support.py`
  - parsing support helpers
- `invoice_parser_extractors.py`
  - item extraction strategies

- `invoice_parser_assessment.py`
  - parser-quality assessment and repair candidate selection

- `invoice_postprocess.py`
  - post-parse orchestration facade
- `invoice_postprocess_country.py`
  - country and numeric cleanup
- `invoice_postprocess_dedup.py`
  - dedup and ordering
- `invoice_postprocess_peer.py`
  - peer repair and shadow pruning

- `extractor/documents/regular/technical_document.py`
  - non-invoice technical document workflow

## Remaining Refactor Targets

The next SRP candidates are:

1. `invoice_cleaner.py`
   - shared heuristics are still dense even after pipeline extraction

2. `invoice_parser_extractors.py`
   - can be split further by schema family if we want smaller strategy modules

## Validation

Validated after refactor:

- `python -m unittest tests.test_invoice_handler -v`
- `python -m unittest tests.test_technical_document_handler -v`
- `python -m unittest tests.test_registry -v`
