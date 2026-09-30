# PO Extractor — purchase order extraction & master-data matching

Upload purchase orders (PDF, PNG/JPG, XLSX) in a web app. Each file is read by a vision-language
model (Qwen3-VL on DeepInfra) into a fixed JSON schema. Deterministic Python code then matches the
customer and every line item against the master Excel files and scores the result. Orders that need
a human are flagged. A reviewer corrects the JSON in the side panel and clicks
**Confirm correct details**.

```
browser ──▶ :8080 nginx (frontend) ──/api──▶ backend (FastAPI) ──▶ Postgres
                                                  │
                                                  ├─ po_extractor package ──HTTPS──▶ DeepInfra (VLM)
                                                  └─ /data/master/*.xlsx (read-only)
```

- **All model inference runs remotely on DeepInfra.** No model weights are downloaded or run on
  your machine; the containers only need a network connection and an API key.
- The model only *extracts*. Validation, matching and scoring are plain Python (`packages/po_extractor`).
- The full spec is in [REQUIREMENTS.md](REQUIREMENTS.md). The decisions agreed during implementation
  are in its **Addendum** at the end.

---

## 1. Prerequisites

- **Docker Desktop** (Apple Silicon or Intel; tested with Docker 29 / Compose v5).
- A **DeepInfra API key**: <https://deepinfra.com/dash/api_keys>.

## 2. Configure

```bash
cp .env.example .env
# edit .env and set at least:
#   DEEPINFRA_API_KEY=<your key>
# for anything beyond local use, also change APP_PASSWORD, JWT_SECRET (32+ random chars) and set DEBUG=false
```

Every setting is listed with a comment in [.env.example](.env.example). Only `.env` differs between
your Mac and a server.

## 3. Run

```bash
docker compose up --build
```

Open **<http://localhost:8080>**. Only port 8080 is published; Postgres and the backend are internal.

On startup the backend checks its config, runs `alembic upgrade head` and verifies that the master
files load. If `DEEPINFRA_API_KEY` or `VLM_MODEL` is missing (or still `changeme`), it stops with:

```
CONFIGURATION ERROR - the backend cannot start:
  - DEEPINFRA_API_KEY is missing (or still the 'changeme' placeholder). ...
```

Data lives in the named Docker volumes `pgdata` (database) and `uploads` (original files). It
survives `docker compose down` and restarts. `docker compose down -v` deletes it.

## 4. Log in

| | |
|---|---|
| URL | <http://localhost:8080> |
| Username | value of `APP_USERNAME` (default `admin`) |
| Password | value of `APP_PASSWORD` (default `admin123`) |

The JWT is kept in memory and in `sessionStorage`, and expires after `JWT_EXPIRE_MINUTES`.

## 5. Using the app

1. Drop one or more files on the upload zone (or click it). Each file appears immediately with a
   spinner; at most 3 are processed at a time.
2. The table shows the order number, customer (or **Not matched: …**), items matched, a status badge
   (green = confident match, amber = low confidence, red = error, grey = processing), the confidence
   score, the main issue and the review state. Tick **Needs review only** to filter.
3. Click a row to open the side panel. It shows the issues, the matched customer master record,
   a per-line item match (✓/✗), the order JSON, and processing details (method, model, tokens, notes).
4. When a file needs review, the JSON is editable. Otherwise click **Edit**. The **Confirm correct
   details** button is disabled while the JSON does not parse. Confirming:
   - stores your version in `reviewed_json` (the AI's `extracted_json` is never changed),
   - re-runs the deterministic validation (no model call) and updates the status,
   - marks the row **✎ Corrected by human** if you changed any value, or **✓ Confirmed by human** if
     you accepted it as-is. The AI's original verdict stays visible ("AI: Low confidence · 43%"),
     together with a table of the fields you changed.

To remove an entry, click 🗑 in its row or **Delete** in the side panel and confirm. This
permanently deletes the database row (including any review) and the stored original file. Rows
that are still processing cannot be deleted until they finish, or until they are older than
10 minutes and so count as stuck.

Rows in **ERROR** with no extraction (e.g. the model was unreachable) show an empty template. You can
fill it in by hand and confirm it the same way.

### What the statuses mean

| `match_result` | meaning |
|---|---|
| FULL_MATCH | customer (number **and** legal name) and every item found in the masters |
| PARTIAL_MATCH | every item found, customer not |
| NO_MATCH | at least one item not found (or inactive) |

`status` is **ERROR** for blocking problems (unsupported/unreadable file, model unavailable, invalid
model output, no line items). It is **LOW_CONFIDENCE** if the match is not full, a sanity check failed,
or the model's lowest `field_confidence` is below `CONFIDENCE_THRESHOLD` (default 0.8). Otherwise it is
**CONFIDENT_MATCH**. `confidence_score` = lowest field confidence × 1.0 / 0.6 / 0.3 (full / partial /
no match).

### How each file type is sent to the model

| Input | What the VLM receives | `extraction_method` |
|---|---|---|
| PDF where every page has ≥ `PDF_MIN_TEXT_CHARS_PER_PAGE` text chars | rendered page images **and** the text layer, in one call; images are authoritative (the text layer of scanned PDFs often has OCR errors) | `pdf_text_vlm` |
| any other PDF (scanned, or has a textless page) | up to `MAX_PDF_PAGES` page images at `PDF_RENDER_DPI` | `pdf_image_vlm` |
| PNG / JPG | the image, long edge ≤ `IMAGE_MAX_EDGE_PX` | `image_vlm` |
| XLSX | every sheet as tab-separated rows (percent/currency cells as displayed) | `excel_text_vlm` |

## 6. Debug mode (development)

`DEBUG=true` is the default in `.env.example`:

- **Backend logs** (`docker compose logs -f backend`) are at DEBUG level. Every line carries the
  request id, e.g. `[req=88bfbc86b91a]`, and the same id is returned in the `X-Request-ID` header
  and in every error body. Model calls log timing, token usage and (truncated) raw output. Base64
  images and API keys are never logged.
- **Error responses** have one JSON shape:
  `{detail, error_type, request_id, errors?, traceback?, file?}`. In DEBUG mode `traceback` holds
  the full Python traceback.
- **In the UI**, every failed request shows a toast with **Technical details** (HTTP status, error
  type, request id, validation errors, traceback). Rows that failed with an unexpected exception
  store the message (plus the traceback in DEBUG) in `error_message`, shown in the side panel under
  *Processing error*. The side panel also has a **Raw results (debug)** section with the full
  `result_json` / `reviewed_result_json`.
- Interactive API docs: <http://localhost:8080/api/docs>.

Set `DEBUG=false` before sharing the deployment: tracebacks are then omitted and the log level is
INFO (override with `LOG_LEVEL`).

## 7. Tests

**In Docker** (no local Python needed; uses the image's dependencies):

```bash
docker compose run --rm --no-deps backend pytest /app/packages/po_extractor/tests   # package unit tests
docker compose run --rm --no-deps backend pytest                                     # backend API tests (SQLite)
docker compose run --rm --no-deps backend pytest /app/packages/po_extractor/tests -m live -v -s   # real DeepInfra calls
```

**Locally** (Python ≥ 3.10):

```bash
python3 -m venv .venv
.venv/bin/pip install -e "packages/po_extractor[dev]" -e "backend[dev]"
(cd packages/po_extractor && ../../.venv/bin/pytest)          # 142 unit tests, no network
(cd backend && ../.venv/bin/pytest)                           # API tests with SQLite + fake extraction
(cd packages/po_extractor && ../../.venv/bin/pytest -m live -v -s)   # uses DEEPINFRA_API_KEY from env or ./.env
```

- Unit tests never touch the network: the OpenAI client is replaced by a fake.
- **Live tests are opt-in** (`-m live`) because they spend tokens. Without a key they are skipped.
  They cover the three acceptance samples plus the three other examples from the master files'
  *Test Scenarios* sheet.

## 8. CLI (debugging the package without the web app)

```bash
# inside the backend container (paths are container paths)
docker compose run --rm --no-deps backend python -m po_extractor \
  "/app/samples/Order example 4.png" \
  --customer-master /data/master/fictional_customer_master.xlsx \
  --item-master /data/master/fictional_item_master.xlsx --pretty

# or locally from the repo root (reads ./.env for DEEPINFRA_API_KEY etc.)
.venv/bin/python -m po_extractor samples/purchase_order_northbridge.xlsx \
  --customer-master data/master/fictional_customer_master.xlsx \
  --item-master data/master/fictional_item_master.xlsx --pretty
```

It prints the `ProcessingResult` JSON to stdout and logs to stderr (`--log-level DEBUG` for more).
It exits with code 2 on a configuration or master-data error.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Backend exits with `CONFIGURATION ERROR` | Set `DEEPINFRA_API_KEY` (not `changeme`) and `VLM_MODEL` in `.env`, then `docker compose up -d`. |
| Rows fail with `MODEL_UNAVAILABLE: DeepInfra rejected the API key (HTTP 401)` | Wrong or revoked key. Fix `DEEPINFRA_API_KEY` in `.env` and run `docker compose up -d backend` (the backend re-reads `.env` on recreate). |
| `MODEL_UNAVAILABLE: Model '…' not found (HTTP 404)` | `VLM_MODEL` is misspelled or not available on your DeepInfra account. Use a model with image input, e.g. `Qwen/Qwen3-VL-235B-A22B-Instruct`. |
| `MODEL_UNAVAILABLE: VLM stopped sending data for 120s` / `did not start answering within 120s` | Responses are streamed; `VLM_TIMEOUT_S` is the longest allowed silence. DeepInfra is overloaded or stuck: retry later, or raise `VLM_TIMEOUT_S`. |
| `MODEL_UNAVAILABLE: VLM did not finish within VLM_TOTAL_TIMEOUT_S=600s` | A very large order (the model writes ~11–13 tokens/s here, ~70–100 tokens per line item). Raise `VLM_TOTAL_TIMEOUT_S` **and** `proxy_read_timeout` in `frontend/nginx.conf` (keep nginx ≥ 60 s higher), or lower `MAX_PDF_PAGES`. |
| `EXTRACTION_SCHEMA_INVALID: Model output was cut off at VLM_MAX_TOKENS=…` | The order has too many lines for the output limit (4096 tokens ≈ 50 lines). Raise `VLM_MAX_TOKENS` (e.g. 8192). |
| UI toast "No response for … it may still be processing" | The browser/nginx connection ended before the backend finished. The row reappears as *Processing* and updates by itself when done. |
| `EXTRACTION_SCHEMA_INVALID` | The model returned unusable JSON `VLM_MAX_RETRIES + 1` times. See *Raw results → meta.debug.last_raw_output*. If the model rejects JSON mode, set `VLM_JSON_MODE=false`. |
| HTTP 400 from DeepInfra mentioning `response_format` | Set `VLM_JSON_MODE=false`. |
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Another process uses 8080 (`lsof -iTCP:8080 -sTCP:LISTEN`). Stop it, or change the published port in `docker-compose.yml` (`"8081:80"`). |
| Health banner "Backend is not healthy … master_data" | A master file is missing or lacks a required column. Check `data/master/` and `docker compose logs backend`. |
| UI toast "Backend unreachable" (HTTP 502) | The backend container is down or restarting: `docker compose ps`, `docker compose logs backend`. |
| Upload rejected with 413 | File is larger than `MAX_UPLOAD_MB` (nginx allows up to 25 MB). |
| Start from an empty database | `docker compose down -v && docker compose up --build` (deletes all rows and uploads). |

## 10. Repository layout

```
.
├── docker-compose.yml          db + backend + frontend (only :8080 published)
├── .env.example                every setting with comments
├── data/master/                customer & item master .xlsx (mounted read-only)
├── samples/                    example purchase orders
├── packages/po_extractor/      framework-free Python package (extract → validate → match → score)
│   ├── src/po_extractor/       extract/ (detect, pdf, excel, image), llm/ (client, prompts),
│   │                           validate/ (normalize, sanity, master_data, matching), scoring, pipeline, cli
│   └── tests/
├── backend/                    FastAPI app, Alembic migration, Dockerfile, tests
└── frontend/                   React + TypeScript (Vite), served by nginx
```

Extending:
- **Unit synonyms**: `UNIT_MAP` in `packages/po_extractor/src/po_extractor/validate/normalize.py`.
- **Sanity checks**: implement the TODO stubs in `validate/sanity.py`, then set `SANITY_CHECKS_MODE=enabled`.
- **Price / UoM checks**: TODO in `validate/matching.py`.
- **Prompt**: `llm/prompts.py`. A test keeps its JSON schema in sync with `schemas.ExtractedOrder`.
