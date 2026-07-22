"""RFQ-AI FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import bom, catalog


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the cache/persistence tables on startup (no-op if they exist).
    init_db()
    yield


app = FastAPI(
    title="RFQ-AI BOM Sourcing API",
    description="Upload a PCB BOM and get back a cost/time optimized, duty-aware sourced BOM.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Allow the Next.js dev server on any local port (it falls back to 3001+
    # when 3000 is taken), so the browser isn't CORS-blocked.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bom.router)
app.include_router(catalog.router)


@app.get("/", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": "rfq-ai", "version": "0.1.0"}


@app.get("/status", tags=["health"])
def status() -> dict:
    """Shows which data sources are live, so you can confirm your keys/config
    were picked up. Handy right after adding a `.env`."""
    from app.config import settings
    from app.services.catalog.registry import registry

    return {
        "database_url": settings.database_url,
        "cache_ttl_hours": settings.cache_ttl_hours,
        "providers": [
            {"name": p.name, "tier": p.tier, "enabled": p.enabled}
            for p in registry.providers
        ],
    }
