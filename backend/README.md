# RFQ-AI Backend

FastAPI service that parses a PCB BOM, fuzzy-matches parts, and returns a
cost/time-optimized, duty-aware sourced BOM.

## Setup

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

- Health check: http://localhost:8000/
- Interactive docs: http://localhost:8000/docs

## Endpoints

- `POST /bom/parse` - multipart file upload (CSV/XLSX) -> detected columns + normalized lines.
- `POST /bom/source` - JSON `{ lines, destination_country, objective }` -> optimized `SourcingResult`.

## Quick test

```bash
curl -F "file=@sample_bom.csv" http://localhost:8000/bom/parse
```

## Data sources (3-tier cascade)

Offers are resolved via `app/services/catalog/registry.py`:

1. **Tier 1** - Nexar/Octopart + official APIs (`nexar_provider.py`). Falls back to
   the built-in demo catalog (`mock_provider.py`) until real keys are added.
2. **Tier 2** - Shopify / WooCommerce platform feeds (`shopify_provider.py`, `woocommerce_provider.py`).
3. **Tier 3** - Scraping (`scrape_provider.py`) - disabled by default, last resort only, consent-first.

These providers are **fully implemented** and activate the moment you supply
credentials/stores. The demo catalog auto-disables once any real source is live.

## Going real (API keys + database)

1. Copy `.env.example` to `.env`.
2. **Nexar (real global offers)** - the key step. At https://portal.nexar.com,
   sign up, create an application, copy the **Client ID** and **Client Secret**
   into `NEXAR_CLIENT_ID` / `NEXAR_CLIENT_SECRET`. The free "Evaluation" app is
   limited to ~100 matched parts total, so test with small BOMs.
3. **Database** - nothing to do: it defaults to a local SQLite file
   (`rfq_ai.db`) that caches offers so repeated lookups don't burn API quota.
   To use a hosted DB instead, set `DATABASE_URL` (e.g. a Postgres URL).
4. **(Optional) Distributor stores** - copy `stores.example.json` to
   `stores.json`, fill in Shopify tokens / WooCommerce keys a distributor issued
   you, and set `STORES_CONFIG=stores.json`.
5. **(Optional) Scraping (Tier 3, last resort)** - set `SCRAPE_ENABLED=true` and
   add sources under the `"scrape"` section of `stores.json`. Consent-first:
   only allow-listed sources are read, only via public structured data
   (Shopify `products.json`), cached + rate-limited, and only when tiers 1-2
   return nothing for a part.
6. Restart the server and open http://localhost:8000/status to confirm which
   sources are `enabled: true`.

## Notes / limitations

- Without a `.env`, distributor data is the demo catalog (`app/data/mock_catalog.json`).
- Duty rates (`app/data/duty_table.json`) and FX rates (`app/services/fx.py`) are
  representative/fixed, not legally binding or live.
- Do not commit `.env`, `stores.json`, or `rfq_ai.db` (they hold secrets / local data).
