# RFQ-AI Frontend

Next.js (App Router) + Tailwind UI for the RFQ-AI BOM sourcing platform.

## Setup

```bash
cd frontend
npm install
```

## Run

```bash
npm run dev
```

Open http://localhost:3000. The backend must be running on http://localhost:8000
(override with `NEXT_PUBLIC_API_URL`).

## Pages

- `/` - landing / value prop.
- `/upload` - drag-drop BOM, review detected columns + lines, pick destination + objective.
- `/results` - optimized sourced BOM: summary cards, per-line chosen supplier with
  source badges, expandable alternates (local vs imported), cost/time toggle.

## Config

- `NEXT_PUBLIC_API_URL` - backend base URL (default `http://localhost:8000`).
