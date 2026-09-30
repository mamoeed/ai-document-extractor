# PO Extractor

Upload purchase orders (PDF, PNG/JPG, XLSX). A vision-language model (Qwen3-VL on DeepInfra) extracts
them to JSON, Python code matches the customer and items against the master Excel files in
`data/master/`, and uncertain orders are flagged for human review. Full spec: [REQUIREMENTS.md](REQUIREMENTS.md).

## Setup

You need Docker (Docker Desktop, or Docker Engine with Compose v2) and a
[DeepInfra API key](https://deepinfra.com/dash/api_keys).

```bash
git clone <this-repo-url> po-extractor && cd po-extractor
cp .env.example .env          # then set DEEPINFRA_API_KEY in .env
docker compose up --build
```

Open <http://localhost:8080> and log in as `admin` / `admin123` (`APP_USERNAME` / `APP_PASSWORD` in `.env`).
Upload files, click a row to review or correct its JSON, and tick rows to download them as JSON.
Example files are in `samples/`.

The model runs on DeepInfra; nothing is downloaded or run locally. Before sharing a deployment,
change `APP_PASSWORD` and `JWT_SECRET`, and set `DEBUG=false` in `.env`.

## Tests

```bash
docker compose run --rm --no-deps backend pytest /app/packages/po_extractor/tests            # no network
docker compose run --rm --no-deps backend pytest                                              # API tests
docker compose run --rm --no-deps backend pytest /app/packages/po_extractor/tests -m live     # calls DeepInfra (paid)
```

## CLI

```bash
docker compose run --rm --no-deps backend python -m po_extractor /app/samples/purchase_order_northbridge.xlsx \
  --customer-master /data/master/fictional_customer_master.xlsx \
  --item-master /data/master/fictional_item_master.xlsx --pretty
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Backend exits with `CONFIGURATION ERROR` | Set `DEEPINFRA_API_KEY` in `.env`. |
| `MODEL_UNAVAILABLE … HTTP 401` | Invalid API key. |
| `MODEL_UNAVAILABLE … not found (HTTP 404)` | Wrong `VLM_MODEL`. |
| `MODEL_UNAVAILABLE … VLM_TIMEOUT_S` or `VLM_TOTAL_TIMEOUT_S` | DeepInfra is slow or the order is very large: raise these in `.env`. |
| `port is already allocated` | Free port 8080, or change `8080:80` in `docker-compose.yml`. |

Logs: `docker compose logs -f backend`. Delete all data: `docker compose down -v`.
