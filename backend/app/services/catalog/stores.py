"""Loads Tier-2 store configuration (Shopify / WooCommerce) from a JSON file.

Point `STORES_CONFIG` at a JSON file shaped like `stores.example.json`. Each
entry is one distributor's store plus the credentials that distributor issued
you. Consent-first: only stores listed here are ever queried.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List

from app.config import settings


@lru_cache(maxsize=1)
def _raw() -> dict:
    path = settings.stores_config
    if not path:
        return {}
    p = Path(path)
    if not p.is_absolute():
        # Resolve relative to the backend/ directory.
        p = Path(__file__).resolve().parents[3] / path
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _clean(entries: List[dict]) -> List[dict]:
    """Drop comment keys (starting with '_') and skip placeholder entries that
    have no base_url, so example/commented rows don't create bogus sources."""
    cleaned: List[dict] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        stripped = {k: v for k, v in entry.items() if not k.startswith("_")}
        if not stripped.get("base_url"):
            continue
        cleaned.append(stripped)
    return cleaned


def shopify_stores() -> List[dict]:
    return _clean(_raw().get("shopify", []))


def woocommerce_stores() -> List[dict]:
    return _clean(_raw().get("woocommerce", []))


def scrape_sources() -> List[dict]:
    """Tier-3 allow-list: only these sources may ever be scraped."""
    return _clean(_raw().get("scrape", []))
