"""Provider that searches the locally-crawled scrape catalog (the DB).

This is the fast path for scraped data: instead of hitting distributor sites on
every BOM lookup, it queries the `scraped_products` table the crawler populated.
The live `ScrapeProvider` remains as a last-resort fallback for parts the local
catalog hasn't harvested yet.
"""
from __future__ import annotations

import re
from typing import List

from sqlalchemy import select

from app.config import settings
from app.db import ScrapedProduct, SessionLocal
from app.models import AccessMethod, Offer, PriceBreak
from app.services.catalog.base import CatalogProvider
from app.services.catalog.relevance import is_relevant
from app.services.catalog.stores import scrape_sources

_MAX_RESULTS_PER_QUERY = 5

# Words that usually indicate an accessory rather than the part itself.
_ACCESSORY_WORDS = {
    "case", "cover", "cable", "holder", "mount", "bracket", "stand", "box",
    "kit", "bundle", "combo", "enclosure", "clip", "screw", "spacer", "acrylic",
    "sticker", "keychain", "bag", "shield", "hat", "expansion",
}


def _tokens(s: str) -> List[str]:
    # Keep decimal values intact (0.1uf stays "0.1uf") so DB LIKE queries
    # match the crawled search_text, and so "0.1uf" ≠ "1uf".
    text = re.sub(r"[^a-z0-9.]+", " ", (s or "").lower())
    return [t.strip(".") for t in text.split() if len(t.strip(".")) >= 2]


def _relevance(row: "ScrapedProduct", tokens: List[str]) -> float:
    """Higher = the product is more likely the queried part (not an accessory)."""
    title_tokens = _tokens(row.title)
    if not title_tokens:
        return -99.0
    matched = sum(1 for t in tokens if any(t == w or t in w for w in title_tokens))
    ratio = matched / len(title_tokens)  # how much of the title is "about" the query
    phrase_bonus = 2.0 if " ".join(tokens) in (row.title or "").lower() else 0.0
    accessory_penalty = 1.5 * sum(1 for w in title_tokens if w in _ACCESSORY_WORDS)
    stock_bonus = 0.5 if row.in_stock else 0.0
    return phrase_bonus + ratio * 3.0 + stock_bonus - accessory_penalty


class LocalCatalogProvider(CatalogProvider):
    tier = 2  # DB-backed catalog is in the fast path (before live scraping)
    access_method = AccessMethod.scrape

    def __init__(self) -> None:
        # Same consent gate as scraping: only active when scraping is enabled
        # and at least one source is allow-listed (and thus crawlable).
        self.enabled = settings.scrape_enabled and bool(scrape_sources())

    @property
    def name(self) -> str:
        return "local-catalog"

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not self.enabled:
            return []

        # Try the MPN's tokens first, then fall back to the description.
        for raw in (mpn, description):
            tokens = _tokens(raw)
            if not tokens:
                continue
            rows = self._query(tokens)
            # Enforce the shared relevance gate so the crawled catalog can't
            # return a tangential product (e.g. a "load cell" for a "10K
            # resistor"). A rejected row becomes an honest "no match".
            rows = [r for r in rows if is_relevant(mpn, description, r.title)]
            if rows:
                return [self._to_offer(r) for r in rows]
        return []

    @staticmethod
    def _query(tokens: List[str]) -> List[ScrapedProduct]:
        stmt = select(ScrapedProduct)
        for tok in tokens:
            stmt = stmt.where(ScrapedProduct.search_text.like(f"%{tok}%"))
        stmt = stmt.limit(80)  # candidate pool; scored in Python below
        with SessionLocal() as db:
            candidates = list(db.scalars(stmt))

        # These candidates are DIFFERENT products (not the same part from many
        # sellers), so keep only the single most-relevant match per store. That
        # way the optimizer compares like-for-like across stores instead of
        # picking whichever loosely-related item happens to be cheapest.
        best: dict[str, tuple[float, ScrapedProduct]] = {}
        for row in candidates:
            score = _relevance(row, tokens)
            if score <= 0:  # drop accessory-only / weak matches
                continue
            if row.source not in best or score > best[row.source][0]:
                best[row.source] = (score, row)

        ranked = sorted(best.values(), key=lambda x: -x[0])
        return [row for _, row in ranked][:_MAX_RESULTS_PER_QUERY]

    @staticmethod
    def _to_offer(row: ScrapedProduct) -> Offer:
        return Offer(
            mpn=row.sku or row.title,
            manufacturer=row.vendor or row.source,
            description=row.title or "",
            distributor=row.source,
            access_method=AccessMethod.scrape,
            authorized=True,
            region=row.region or "IN",
            currency=row.currency or "INR",
            price_breaks=[PriceBreak(qty=1, unit_price=row.price)],
            stock=9999 if row.in_stock else 0,
            lead_time_days=4,
            moq=1,
            product_url=row.product_url or "",
        )
