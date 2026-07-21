"""Tier-3 scraping adapter (stub) - LAST RESORT, DISABLED BY DEFAULT.

Per the project's Don'ts: scraping is never in the fast path and is only used
when tiers 1-2 return nothing for a part AND the specific source is
authorized. Any offers it produces are tagged authorized=False unless the
source is on the allow-list, so the registry will drop them.
"""
from __future__ import annotations

from typing import List

from app.models import AccessMethod, Offer
from app.services.catalog.base import CatalogProvider


class ScrapeProvider(CatalogProvider):
    tier = 3
    access_method = AccessMethod.scrape
    # Off by default. Enable only with an explicit, per-source allow-list.
    enabled = False

    def __init__(self, authorized_sources: List[str] | None = None) -> None:
        self.authorized_sources = authorized_sources or []

    @property
    def name(self) -> str:
        return "scrape"

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not self.enabled or not self.authorized_sources or not mpn:
            return []
        # TODO: for each permitted source, read structured data (products.json /
        # JSON-LD) behind a cache with TTL + rate limiting. Only reached as a
        # fallback when APIs/feeds have no data for this part.
        return []
