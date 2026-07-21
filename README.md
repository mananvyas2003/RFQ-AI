# RFQ-AI - AI BOM Sourcing Platform

Upload a PCB Bill of Materials (BOM) and get back a cost- or time-optimized,
duty-aware **sourced BOM**. Parts are fuzzy-matched to real manufacturer part
numbers, priced across global and Indian suppliers, and ranked on true landed
cost (price + shipping + import duty). India-first, priced in INR.

See [PLAN.md](PLAN.md) for the full design and roadmap.

## Structure

```
RFQ-AI/
  backend/    FastAPI service (parse, match, optimize, duty)
  frontend/   Next.js + Tailwind UI
  PLAN.md     Design document
```

## Quick start

Two terminals.

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, upload `backend/sample_bom.csv` (also downloadable
from the UI), and view the optimized result.

## How it works

1. **Parse** - CSV/XLSX read; columns (MPN, qty, description...) auto-detected.
2. **Match** - messy/partial entries fuzzy-matched to canonical parts with a confidence score.
3. **Source** - offers aggregated via a 3-tier cascade (Nexar/APIs -> Shopify/WooCommerce feeds -> scraping as last resort).
4. **Optimize** - best offer per line by cost or time, on landed cost.
5. **Duty** - import duty computed per destination + HS code + ship-from; domestic offers = zero duty.

## Data sources

MVP runs on a mixed-source mock catalog. Real providers are ready-to-activate
stubs (`backend/app/services/catalog/`): Nexar/Octopart, Shopify, WooCommerce,
and a consent-first, disabled-by-default scrape adapter.

## Notes / limitations (MVP)

- Distributor data is mocked; FX and duty rates are representative/fixed, not live or legally binding.
- No authentication, database, or ordering yet (by design for the MVP).
