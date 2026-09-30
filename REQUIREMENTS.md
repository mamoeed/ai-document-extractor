# REQUIREMENTS — Purchase Order Extraction & Master-Data Matching

This document is the build spec for an AI coding agent. Build exactly what is described here. Where something is ambiguous, follow the "Decisions" section. If code already exists in the repo, refactor it into the structure below instead of rewriting it.

> **See the [Addendum](#addendum--decisions-agreed-during-implementation-2026-09-28) at the end** for changes agreed with the product owner during implementation. The addendum takes precedence where it differs from the sections above it.

---

## 0. Goal in one paragraph

A user logs in to a web app and uploads one or more purchase orders (PDF, PNG, or Excel). For each file, a Python package does four things in order:

1. It extracts the order into a fixed JSON schema.
2. It runs sanity checks on the extracted fields.
3. It matches the customer against a customer master Excel file.
4. It matches each line item against an item master Excel file.

The package then returns a status, a confidence score, and a list of issues. A FastAPI backend stores every result in Postgres. The frontend shows all processed files in a table, and clicking a row opens the JSON in a side panel. When human review is needed, the user edits the JSON and clicks **"Confirm correct details"**. That saves the edits and marks the row as human-reviewed. Everything runs locally on a MacBook (Apple Silicon) with `docker compose up`, and the same setup is used for later deployment.

---

## 1. Decisions (resolve ambiguity with these)

| # | Decision |
|---|---|
| D1 | **One deployment path**: Docker Compose. The same compose file is used on the Mac and on the server; only `.env` differs. Do not add a second "non-Docker" run path for the app. (The package CLI in §3.8 is for debugging only.) |
| D2 | **No Docling and no other OCR or parsing service.** The only external service is the Qwen VLM on DeepInfra. Python extracts raw content locally: PDF text or page images with `pypdfium2`, Excel cells with `openpyxl`. The **VLM does all field extraction** for every file type. |
| D3 | **One model for everything**: an OpenAI-compatible client pointed at DeepInfra. The same `VLM_MODEL` handles image input (scanned PDFs, PNGs) and text-only input (text PDFs, Excel). The model is selected by env var. |
| D4 | **The LLM only extracts. All validation, matching, and scoring is deterministic Python.** Never ask the model whether a customer or item "matches". |
| D5 | Processing is **synchronous per file**. The frontend sends one request per file, in parallel with at most 3 in flight. The backend inserts the DB row as `PROCESSING` first, then updates it, so a crash leaves a visible row. |
| D6 | Login uses **one hardcoded user** from env (`APP_USERNAME` / `APP_PASSWORD`), with a signed JWT carried as a bearer token. There are no user tables. |
| D7 | Master files are read-only inputs mounted into the backend container. The package receives their **paths** as arguments. |

---

## 2. Repository layout

```
/
├── README.md                     # setup + run + test instructions (see §7)
├── REQUIREMENTS.md               # this file
├── docker-compose.yml
├── .env.example                  # every env var from §6, with safe placeholders
├── .gitignore                    # must ignore .env, data/uploads/
├── data/
│   ├── master/                   # fictional_customer_master.xlsx, fictional_item_master.xlsx
│   └── uploads/                  # runtime file storage (docker volume, gitignored)
├── samples/                      # test POs: clearline PDF, northbridge PNG, northbridge XLSX
├── packages/po_extractor/        # the Python package (§3)
│   ├── pyproject.toml
│   ├── src/po_extractor/
│   │   ├── __init__.py           # exports process_file, validate_order, Settings
│   │   ├── config.py             # pydantic-settings, reads env
│   │   ├── schemas.py            # all Pydantic models (§3.2, §3.6)
│   │   ├── pipeline.py           # process_file / validate_order orchestration
│   │   ├── extract/
│   │   │   ├── detect.py         # file type detection (magic bytes, not just extension)
│   │   │   ├── pdf.py            # text-layer check, text extraction, page rendering
│   │   │   ├── excel.py          # openpyxl → text
│   │   │   └── image.py          # resize/encode for VLM
│   │   ├── llm/
│   │   │   ├── client.py         # OpenAI SDK → DeepInfra, retries, JSON parsing
│   │   │   └── prompts.py        # system + user prompts (§3.4)
│   │   ├── validate/
│   │   │   ├── normalize.py      # names, numbers, units, ids
│   │   │   ├── sanity.py         # mock sanity checks (§3.5.1)
│   │   │   ├── master_data.py    # load + cache master Excel files
│   │   │   └── matching.py       # customer + item matching
│   │   ├── scoring.py            # status + confidence (§3.7)
│   │   └── cli.py                # python -m po_extractor ...
│   └── tests/
├── backend/
│   ├── Dockerfile                # build context = repo root; pip installs packages/po_extractor
│   ├── pyproject.toml
│   ├── alembic/                  # one initial migration
│   └── app/ (main.py, auth.py, db.py, models.py, routes/, services/)
└── frontend/
    ├── Dockerfile                # multi-stage: build React → serve with nginx
    ├── nginx.conf                # serves SPA, proxies /api → backend:8000
    └── src/
```

---

## 3. Package: `po_extractor`

### 3.1 Public API

```python
from po_extractor import process_file, validate_order, Settings

result: ProcessingResult = process_file(
    file_path: str | Path,
    customer_master_path: str | Path,
    item_master_path: str | Path,
    settings: Settings | None = None,     # default: Settings() from env
)

# Re-run steps 2–4 on a (human-edited) order without calling any model:
result: ProcessingResult = validate_order(
    order: ExtractedOrder,
    customer_master_path, item_master_path, settings=None,
)
```

- `process_file` must **never raise** for problems with the document. It returns `status="ERROR"` with issues instead. It raises only for programmer or config errors, such as a missing API key or a master file path that does not exist.
- Keep it framework-free: the package must not import FastAPI or SQLAlchemy.

### 3.2 Extraction schema (`ExtractedOrder`)

All fields are optional unless marked required. Dates use ISO `YYYY-MM-DD`. Numbers are JSON numbers with a dot as the decimal separator.

```json
{
  "document": {
    "order_number": "string (required)",
    "order_date": "date",
    "requested_delivery_date": "date",
    "currency": "ISO 4217, e.g. EUR"
  },
  "customer": {
    "customer_number": "string (required) — the number the ISSUER gives as 'Customer no./Customer number'",
    "legal_name": "string (required) — legal name of the company ISSUING the PO",
    "street": "string", "postcode": "string", "city": "string", "country": "string",
    "contact_name": "string", "email": "string", "phone": "string"
  },
  "delivery_address": { "name": "", "street": "", "postcode": "", "city": "", "country": "" },
  "line_items": [
    {
      "position": "string",
      "item_number": "string (required) — value from the document's main 'Item no.' column",
      "reference_number": "string — any other per-line number ('Your item no.', 'Your Order no.', drawing no.)",
      "description": "string",
      "quantity": "number",
      "unit": "string (as printed)",
      "unit_price": "number",
      "discount_percent": "number",
      "line_net_amount": "number"
    }
  ],
  "totals": { "net_amount": "number", "vat_percent": "number", "vat_amount": "number", "gross_amount": "number" },
  "field_confidence": {
    "order_number": "0..1", "customer_number": "0..1", "legal_name": "0..1",
    "line_items": "0..1 (lowest across all item_number/quantity values)"
  },
  "extraction_notes": "string — anything the model found unclear"
}
```

Validate the model's output with Pydantic. Coerce IDs to strings: `58264`, not `58264.0`.

### 3.3 Step 1 — Extraction

The first step is file type detection. Supported types are `.pdf`, `.png` (also accept `.jpg` / `.jpeg`), and `.xlsx`. Anything else returns `ERROR` + `UNSUPPORTED_FILE_TYPE`.

| Input | Flow |
|---|---|
| **PDF** | 1. Open with `pypdfium2` and count extracted text characters per page. 2. If every page has at least `PDF_MIN_TEXT_CHARS_PER_PAGE` characters, the PDF is **programmatically readable**: extract the text of each page with `pypdfium2`, join the pages under `## Page N` headers, and send the text to the VLM (**text-only** message). 3. Otherwise the PDF is **not readable** (scanned): render up to `MAX_PDF_PAGES` pages at `PDF_RENDER_DPI` to PNG and send all page images in **one** VLM call. |
| **PNG/JPG** | Downscale so the long edge is at most `IMAGE_MAX_EDGE_PX`, base64-encode it, and send it to the VLM. |
| **XLSX** | Read with `openpyxl` (`data_only=True`). For every sheet, emit the non-empty rows as tab-separated lines under a `## Sheet: <name>` header. Truncate at `MAX_TEXT_CHARS`. Send the result to the VLM (**text-only** message). |

VLM call requirements (same model and client for text-only and image messages):
- Use the OpenAI Python SDK with `base_url=DEEPINFRA_BASE_URL` and `api_key=DEEPINFRA_API_KEY`.
- Set `temperature=0` and `response_format={"type": "json_object"}`.
- Strip any code fences from the response before running `json.loads`.
- On invalid JSON or a Pydantic error, retry up to `VLM_MAX_RETRIES` times. Each retry appends the validation error to the prompt. If the output is still invalid, return `ERROR` + `EXTRACTION_SCHEMA_INVALID`.
- Timeout is `VLM_TIMEOUT_S`. On timeout or HTTP error, return `ERROR` + `MODEL_UNAVAILABLE`.
- Record `extraction_method` (`pdf_text_vlm` | `pdf_image_vlm` | `image_vlm` | `excel_text_vlm`), `model_name`, and the token usage.

### 3.4 Prompt rules (put these in `prompts.py`)

The system prompt must state:
- **We are the supplier, Aurora Parts.** The **customer** is the company that *issued* the PO, identified by its letterhead, logo, footer, or sender line. The recipient address block is us, so never use it as the customer.
- `customer_number` comes from the label "Customer no." or "Customer number". Do not use "Supplier number".
- `item_number` comes from the main "Item no." column. Numbers labelled "Your item no.", "Your Order no.", or "Drawing no." go into `reference_number`.
- Convert German number formats to plain numbers: `1.118,00` → `1118.00` and `5,00` → `5`. Convert dates to ISO.
- Copy values exactly as printed. Do not invent or correct anything; use `null` when a value is not present.
- Fill `field_confidence` honestly and return **only** the JSON object.

Include the JSON schema from §3.2 in the prompt.

### 3.5 Steps 2–4 — Validation (deterministic)

**Normalization** (`normalize.py`) is applied to both the document side and the master side before any comparison:
- **IDs**: convert to string, strip, and drop a trailing `.0`.
- **Names**: apply Unicode NFKC, casefold, collapse whitespace, and strip. This makes `ClearLine Hygiene GmbH` equal to `Clearline Hygiene GmbH`.
- **Units**: map to the master's base unit of measure. `Stk`, `Stück`, `pcs`, and `pc` become `pc`; `canisters` becomes `canister`; `sets` becomes `set`. Keep the mapping as a dict so it can be extended.

#### 3.5.1 Sanity checks — MOCK for now
- Signature: `run_sanity_checks(order: ExtractedOrder) -> list[Issue]`.
- The mock returns `[]` when `SANITY_CHECKS_MODE=mock`, which is the default.
- Leave these checks as TODO stubs with docstrings, to be implemented later: quantity × unit price = line net (±0.01); the line nets sum to the net total; net × VAT = VAT amount; net + VAT = gross; the delivery date is on or after the order date.

#### 3.5.2 Master data loading (`master_data.py`)
- Customer file: sheet `Customer Master`, falling back to the first sheet if it is missing.
- Item file: sheet `Item Master`, with the same fallback.
- The files have title rows above the header. **Detect the header row** by scanning the first 10 rows for the required column names. Ignore the `Test Scenarios` sheets.
- Required columns:
  - Customer file: `Customer no.`, `Legal name`, `Active`.
  - Item file: `Source item no.`, `Description`, `Base UoM`, `Net price EUR`, `Active`.
- If a required column is missing, raise `MasterDataError`. The backend reports this as a 500 with a clear message.
- Cache the loaded data keyed by `(path, mtime)`.

#### 3.5.3 Customer match (`matching.py`)
- Key: **(customer_number, normalized legal_name) together.** Customer no. `48326` appears twice in the master on purpose (ClearLine and Northstar), so the number alone is never enough.
- Outcomes:
  - Both fields match a row → `customer_matched = true`, and return the master row.
  - The number exists but no row has that name → issue `CUSTOMER_NAME_MISMATCH`. The issue lists the master names for that number.
  - The number is not in the master → issue `CUSTOMER_NOT_FOUND`.
  - The customer number or legal name was not extracted → issue `CUSTOMER_FIELDS_MISSING`.

#### 3.5.4 Item match
- For each line: look up `item_number` in `Source item no.` **and** require `Active == "Yes"` (case-insensitive).
- Outcomes:
  - Found and active → matched, and return the master row.
  - Found but inactive → issue `ITEM_INACTIVE`, not matched.
  - Not found → issue `ITEM_NOT_FOUND`, not matched.
- Return a per-line match list and `items_matched / items_total`.
- Out of scope for now: price and unit-of-measure comparison. Leave a TODO.

### 3.6 Output schema (`ProcessingResult`)

```json
{
  "status": "CONFIDENT_MATCH | LOW_CONFIDENCE | ERROR",
  "match_result": "FULL_MATCH | PARTIAL_MATCH | NO_MATCH | null",
  "confidence_score": 0.0,
  "needs_human_review": true,
  "issues": [
    { "code": "ITEM_NOT_FOUND", "severity": "error|warning|info",
      "message": "Item 628450 (line 2) not found in item master",
      "field": "line_items[1].item_number" }
  ],
  "extracted": { "...ExtractedOrder..." },
  "customer_match": { "matched": true, "master_record": { }, "candidates": [ ] },
  "item_matches": [ { "line_index": 0, "item_number": "7842136", "matched": true, "master_record": { } } ],
  "summary": { "customer": "ClearLine Hygiene GmbH (48326)", "items_matched": 3, "items_total": 3 },
  "meta": { "file_name": "", "file_type": "", "extraction_method": "", "model_name": "", "duration_ms": 0 }
}
```

Issue codes to implement:

| Kind | Codes |
|---|---|
| **Errors (blocking)** | `UNSUPPORTED_FILE_TYPE`, `FILE_UNREADABLE`, `MODEL_UNAVAILABLE`, `EXTRACTION_SCHEMA_INVALID`, `NO_LINE_ITEMS` |
| **Match issues** | `CUSTOMER_NOT_FOUND`, `CUSTOMER_NAME_MISMATCH`, `CUSTOMER_FIELDS_MISSING`, `ITEM_NOT_FOUND`, `ITEM_INACTIVE` |
| **Quality issues** | `LOW_EXTRACTION_CONFIDENCE`, `SANITY_CHECK_FAILED` |

### 3.7 Scoring rules (`scoring.py`)

**`match_result`** (same meanings as the master files' Test Scenarios sheet):
- `FULL_MATCH`: the customer matched and every item matched.
- `PARTIAL_MATCH`: every item matched, but the customer did not.
- `NO_MATCH`: at least one item did not match.

**`status`**, evaluated in this order:
1. `ERROR`: any blocking error from the list above. In this case `match_result` is `null`.
2. `LOW_CONFIDENCE`: any of the following is true:
   - `match_result != FULL_MATCH`
   - any sanity issue exists
   - the minimum of `field_confidence` is below `CONFIDENCE_THRESHOLD`, which adds `LOW_EXTRACTION_CONFIDENCE`
3. `CONFIDENT_MATCH`: otherwise.

**Other outputs:**
- `confidence_score` = `min(field_confidence values)` × a factor of 1.0 for `FULL_MATCH`, 0.6 for `PARTIAL_MATCH`, or 0.3 for `NO_MATCH`. It is 0 for `ERROR`. Round to 2 decimals.
- `needs_human_review` = `status != CONFIDENT_MATCH`.

### 3.8 CLI

```
python -m po_extractor <file> --customer-master <path> --item-master <path> [--pretty]
```
The CLI prints the `ProcessingResult` JSON.

---

## 4. Backend: FastAPI

### 4.1 Endpoints (all under `/api`; everything except login and health needs a bearer token)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Takes `{username, password}` and returns `{access_token}`. Returns 401 on wrong credentials. |
| GET | `/api/health` | Checks the DB and that both master files load. Returns `{ok, db, master_data}`. It does not call the VLM, to avoid spending tokens. |
| POST | `/api/files` | Multipart upload of **one** file. Steps: 1. Save to `UPLOAD_DIR/<uuid>/<original_name>`. 2. Insert a row with `status=PROCESSING`. 3. Call `process_file(...)` in a threadpool (`run_in_threadpool`). 4. Update the row. 5. Return the row. Rejects files over `MAX_UPLOAD_MB` with 413. |
| GET | `/api/files` | Lists all rows, newest first, **without** the large JSON columns. |
| GET | `/api/files/{id}` | Returns the full row, including the extracted, reviewed, and result JSON. |
| GET | `/api/files/{id}/original` | Streams the original file (for a preview link). |
| PUT | `/api/files/{id}/review` | Takes `{order: ExtractedOrder}`. Validates it with Pydantic (422 on error), runs `validate_order(...)`, and saves the result to the review columns. Sets `human_reviewed=true`, `needs_human_review=false`, `reviewed_by`, and `reviewed_at`. Returns the row. |

Master file paths come from env (`CUSTOMER_MASTER_PATH`, `ITEM_MASTER_PATH`).

### 4.2 Postgres table `processed_files`

| column | type | notes |
|---|---|---|
| id | uuid pk | |
| original_filename | text | |
| stored_path | text | |
| file_type | text | pdf / png / xlsx |
| file_sha256 | text | display only; do not deduplicate |
| uploaded_by | text | |
| uploaded_at | timestamptz | default now() |
| status | text | `PROCESSING`, `CONFIDENT_MATCH`, `LOW_CONFIDENCE`, `ERROR` |
| match_result | text null | |
| confidence_score | numeric(3,2) null | |
| needs_human_review | bool | |
| human_reviewed | bool | default false |
| order_number | text null | denormalized for the table view |
| customer_label | text null | e.g. "ClearLine Hygiene GmbH (48326)" or the extracted name when unmatched |
| items_matched / items_total | int null | |
| issues | jsonb | list of Issue |
| extracted_json | jsonb | **original model output, never overwritten** |
| result_json | jsonb | full ProcessingResult from the first run |
| reviewed_json | jsonb null | human-edited ExtractedOrder |
| reviewed_result_json | jsonb null | ProcessingResult of `validate_order` on the edit |
| reviewed_by / reviewed_at | text / timestamptz null | |
| extraction_method, model_name | text | |
| duration_ms | int | |
| error_message | text null | set if an unexpected exception happens (row → ERROR) |

- Create the table with an Alembic migration that runs on backend start (`alembic upgrade head`).
- On startup, set any leftover `PROCESSING` rows older than 10 minutes to `ERROR` with the message "interrupted".

---

## 5. Frontend: React + TypeScript (Vite), served by nginx

**Login page**
- Username and password fields.
- Store the JWT in memory plus `sessionStorage`.
- On a 401, redirect to login.

**Main page**
- **Upload zone**: supports drag-and-drop and a file picker, with multi-select. Accepts `.pdf,.png,.jpg,.jpeg,.xlsx`. It sends one `POST /api/files` per file, at most 3 at a time. Each file appears in the table immediately with a spinner until its response arrives.
- **Table**: loaded from `GET /api/files` on login, so state persists across sessions. Columns:
  - File name
  - Uploaded at
  - Order no.
  - Customer (matched label or "Not matched: <name>")
  - Items (e.g. `2/3`)
  - **Status badge** (green = Confident match, amber = Low confidence, red = Error, grey = Processing)
  - Confidence (%)
  - Main issue (the first issue's message, with a count of the others)
  - **Human reviewed** (✓ plus the reviewer and time)
- Sorting is by upload time, newest first. Offer a filter for "Needs review".

**Side panel** (opens on row click)
- Header: file name, status, confidence, and a link to open the original file.
- Issues list, with severity icons.
- Match summary: the customer master record found (or not found) and a per-line item match ✓/✗.
- **JSON view** of the order. It shows `reviewed_json` if one exists, otherwise `extracted_json`.
  - When `needs_human_review` is true or the user clicks "Edit", the JSON becomes editable. A code editor such as CodeMirror is fine.
  - On every change, validate that the JSON parses. Disable the save button while it is invalid.
  - The **"Confirm correct details"** button calls `PUT /api/files/{id}/review`. On success, it updates the row and the panel with the new status from re-validation.

Keep the styling simple and clean. No component library is required.

---

## 6. Configuration (`.env.example`)

```bash
# --- LLM / VLM (DeepInfra, OpenAI-compatible) ---
DEEPINFRA_API_KEY=changeme
DEEPINFRA_BASE_URL=https://api.deepinfra.com/v1/openai
VLM_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct   # any DeepInfra model with image input
VLM_TEMPERATURE=0
VLM_MAX_TOKENS=4096
VLM_TIMEOUT_S=120
VLM_MAX_RETRIES=2

# --- Extraction tuning ---
PDF_MIN_TEXT_CHARS_PER_PAGE=50
PDF_RENDER_DPI=200
MAX_PDF_PAGES=5
IMAGE_MAX_EDGE_PX=2000
MAX_TEXT_CHARS=60000
CONFIDENCE_THRESHOLD=0.8
SANITY_CHECKS_MODE=mock

# --- Master data (paths inside backend container) ---
CUSTOMER_MASTER_PATH=/data/master/fictional_customer_master.xlsx
ITEM_MASTER_PATH=/data/master/fictional_item_master.xlsx

# --- App ---
APP_USERNAME=admin
APP_PASSWORD=admin123
JWT_SECRET=change-this-long-random-string
JWT_EXPIRE_MINUTES=480
UPLOAD_DIR=/data/uploads
MAX_UPLOAD_MB=20

# --- Database ---
POSTGRES_USER=po
POSTGRES_PASSWORD=po
POSTGRES_DB=po
DATABASE_URL=postgresql+psycopg://po:po@db:5432/po
```

The backend must fail fast at startup with a clear message if `DEEPINFRA_API_KEY` or `VLM_MODEL` is missing.

---

## 7. Deployment: Docker Compose (Mac-first, same file for deploy)

| service | image / build | notes |
|---|---|---|
| `db` | `postgres:16` | named volume `pgdata`; healthcheck `pg_isready` |
| `backend` | `./backend/Dockerfile` (context `.`) | depends on db healthy; mounts `./data/master:/data/master:ro` and volume `uploads:/data/uploads`; runs migrations then `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `frontend` | `./frontend/Dockerfile` | nginx on port 80, published as **`8080:80`**; proxies `/api` → `backend:8000`, with `client_max_body_size 25m` and `proxy_read_timeout 300s` |

- Only port **8080** is published. The user opens **http://localhost:8080**.
- The backend image needs `libmagic`, if used for file detection. `pypdfium2` wheels include the binary, so no system poppler is needed.
- The README must cover:
  1. Prerequisites: Docker Desktop and a DeepInfra API key.
  2. `cp .env.example .env` and fill in the keys.
  3. `docker compose up --build`.
  4. That all model inference happens remotely on DeepInfra, so no model weights are downloaded or run locally.
  5. Login credentials.
  6. How to run tests.
  7. How to use the CLI.
  8. Troubleshooting: 401 from DeepInfra (bad key), model not found (wrong `VLM_MODEL`), timeouts, and port conflicts.

---

## 8. Tests & acceptance criteria

**Unit tests** (pytest, no network; mock the VLM client):
- Normalization: German numbers, IDs (`58264.0` becomes `"58264"`), name casefolding, and the unit map.
- Master loading: detects the header row under the title rows and ignores the `Test Scenarios` sheet.
- Customer match:
  - `48326` + ClearLine → matched.
  - `48326` + Northstar → matched to a **different** row.
  - `48326` + "Some Other GmbH" → `CUSTOMER_NAME_MISMATCH`.
  - `58264` → `CUSTOMER_NOT_FOUND`.
- Item match:
  - `845271`, `725904`, `725918`, and `7842136` → found.
  - `628450` → `ITEM_NOT_FOUND`.
  - Add an inactive fixture row → `ITEM_INACTIVE`.
- Scoring: every rule in §3.7.
- File detection: a `.txt` file → `UNSUPPORTED_FILE_TYPE`, and a corrupt PDF → `FILE_UNREADABLE`.

**Integration tests** (marked `@pytest.mark.live`, skipped unless `DEEPINFRA_API_KEY` is set) run `process_file` on `samples/`:

| Sample | Expected extraction | match_result | status |
|---|---|---|---|
| ClearLine PDF (text layer → text to VLM) | order `OR2607421`, customer `48326` / ClearLine Hygiene GmbH, 3 items | FULL_MATCH | CONFIDENT_MATCH |
| Northbridge PNG (VLM) | order `PO-7642091`, customer `58264` / Northbridge Catering Systems Ltd., 1 item `7842136` (`628450` in `reference_number`) | PARTIAL_MATCH | LOW_CONFIDENCE, issue `CUSTOMER_NOT_FOUND` |
| Northbridge XLSX (Excel text) | order `PO-7642091`, customer `58264`, 2 items | NO_MATCH | LOW_CONFIDENCE, issues `CUSTOMER_NOT_FOUND` + `ITEM_NOT_FOUND` (628450) |

**End-to-end definition of done:**
1. `docker compose up --build` on a clean Mac starts all 3 services healthy.
2. Log in at `localhost:8080`, upload all 3 samples at once, and all 3 rows appear with the statuses above.
3. Clicking a row shows the issues and JSON. Editing the Northbridge PNG JSON and clicking "Confirm correct details" sets **Human reviewed ✓** and stores `reviewed_json`, while `extracted_json` stays unchanged.
4. Log out, restart the containers, and log in again: all rows and review states are still there.
5. No API keys appear in the repo, the logs, or the frontend bundle.

---

## 9. Out of scope (leave TODOs, do not build)

Real sanity checks, price and unit-of-measure validation against the master, multiple users or roles, async job queues, master-data upload through the UI, and editing master data.

---

## Addendum — decisions agreed during implementation (2026-09-28)

These were raised by the implementing agent and approved by the product owner. They take precedence over the sections above.

| # | Change | Why |
|---|---|---|
| A1 | **PDFs with a text layer send the text *and* the rendered page images in one VLM call** (still recorded as `extraction_method = pdf_text_vlm`). The prompt tells the model the images are authoritative and the text layer is only a hint for exact digits. Scanned PDFs (§3.3 rule unchanged) send images only. | The sample PDFs are scans with an OCR text layer that contains errors ("Northstar Commercial Kitrnens Ltd.", "ltem no.", "Oty") and scrambles table columns. Text-only extraction would copy those errors and break customer matching (e.g. SC-02). |
| A2 | Blank pages are **not** skipped: the §3.3 rule stays as written (any page under `PDF_MIN_TEXT_CHARS_PER_PAGE` sends the whole PDF down the image path, and every page up to `MAX_PDF_PAGES` is sent). | Owner's decision: an apparently blank page may still carry content. |
| A3 | **Human review keeps the AI's original verdict visible.** New columns: `ai_status`, `ai_confidence_score` (first-run values, never overwritten), `human_corrected` (true if the reviewer changed any value other than `field_confidence` / `extraction_notes`) and `review_changes` (list of `{path, before, after}`). `validate_order(..., human_verified=True)` treats human-confirmed values as confidence 1.0 and sets `ProcessingResult.human_verified = true`. The UI shows "✎ Corrected by human" or "✓ Confirmed by human", the AI result → reviewed result, and a table of changed fields. | Make it clear that the AI was (e.g.) low-confidence and a human then corrected or confirmed the data. |
| A4 | Name normalization **also replaces punctuation with spaces** before comparing (`Ltd.` = `Ltd`). | VLMs often add or drop punctuation in legal names. |
| A5 | `DEBUG=true` (default in `.env.example` for development): DEBUG-level logs with request ids, and error responses / error rows include exception type and traceback, shown in the UI under "Technical details". Set `DEBUG=false` for shared deployments. | Owner is in development and wants errors visible in the API logs and on screen. |
| A6 | **Delete from the UI**: `DELETE /api/files/{id}` (auth required) removes the row, including any review, and the folder `UPLOAD_DIR/<id>/`. It returns 204, 404 if unknown, and 409 while the row is `PROCESSING` and younger than 10 minutes. The UI offers it per table row and in the side panel, behind a confirmation dialog. | Requested by the owner on 2026-09-29. |
| A7 | **Streamed VLM responses and two timeouts** (replaces the single `VLM_TIMEOUT_S` total timeout of §3.3): `VLM_TIMEOUT_S` (default 120) is the longest allowed silence while streaming; new `VLM_TOTAL_TIMEOUT_S` (default 600) caps all model calls for one file. Timed-out requests are not re-sent; 429/5xx/connection errors are retried once. Output cut off at `VLM_MAX_TOKENS` fails fast with a clear message instead of being retried. nginx `proxy_read_timeout` raised to 660 s. The prompt asks for minified JSON (fewer output tokens). | Large orders (e.g. 22 lines ≈ 3 min at DeepInfra's ~12 tokens/s) timed out at 120 s; requested by the owner 2026-09-29. |
| A8 | Prompt: `item_number` is the value explicitly labelled "Item no." (column or inline); an unlabelled manufacturer/part number goes to `reference_number`. | The Northstar PDF had its item and manufacturer numbers swapped (NO_MATCH instead of FULL_MATCH). |

Smaller implementation choices (no owner decision needed): file type detection uses pure-Python magic-byte checks (no libmagic); rendered PDF pages are also capped at `IMAGE_MAX_EDGE_PX`; Excel cells are rendered as displayed for percent/currency formats (`0.19` with `0%` → `19%`); a missing order number or an unreported `field_confidence` value counts as confidence 0; live tests are deselected by default and run with `pytest -m live`; `VLM_JSON_MODE` (default true) can switch off `response_format` for models that reject it.
