"""Tier-3 scraping adapter - LAST RESORT, OFF BY DEFAULT.

Per the project's consent-first policy, scraping is never in the fast path: the
registry only consults this tier when tiers 1-2 return nothing for a part. It is
gated twice:
  1. `SCRAPE_ENABLED=true` in the environment (master switch), AND
  2. the source must be listed in the "scrape" section of STORES_CONFIG
     (per-source allow-list - your assertion that this source permits it).

Live search supports Shopify search-suggest JSON and WooCommerce Store API.
Custom `html_sitemap` sources are harvested offline by `crawl.py` into the local
catalog (Tier 2) instead of being hit live per BOM line.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Dict, List

import httpx

from app.config import settings
from app.models import AccessMethod, Offer, PriceBreak
from app.services.cache import get_cached_offers, set_cached_offers
from app.services.catalog.base import CatalogProvider
from app.services.catalog.relevance import is_relevant
from app.services.catalog.stores import scrape_sources

logger = logging.getLogger(__name__)
_USER_AGENT = "RFQ-AI/1.0 (+sourcing; contact site owner if this is unwanted)"

# Per-host timestamp of the last request, for polite rate limiting.
_last_hit: Dict[str, float] = {}
_lock = threading.Lock()


class ScrapeSource:
    def __init__(self, name: str, base_url: str, platform: str = "shopify_json",
                 region: str = "IN", currency: str = "INR", lead_time_days: int = 5,
                 **_extra) -> None:
        # Ignore crawler-only keys from stores.json (max_products, sitemaps, …).
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.platform = platform
        self.region = region
        self.currency = currency
        self.lead_time_days = lead_time_days


class ScrapeProvider(CatalogProvider):
    tier = 3
    access_method = AccessMethod.scrape

    def __init__(self, sources: List[ScrapeSource] | None = None) -> None:
        if sources is None:
            sources = [ScrapeSource(**s) for s in scrape_sources()]
        self.sources = sources
        # Double gate: master switch AND at least one allow-listed source.
        self.enabled = settings.scrape_enabled and bool(self.sources)

    @property
    def name(self) -> str:
        return "scrape"

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not self.enabled:
            return []

        mpn = (mpn or "").strip()
        description = (description or "").strip()
        # Description-only BOM lines (no MPN) are valid — hobby stores list
        # parts by common name. Previously we bailed on empty MPN and those
        # lines were always reported as unsourced.
        if not mpn and not description:
            return []

        cache_key = mpn or description
        cached = get_cached_offers(self.name, cache_key)
        if cached is not None:
            # Filter cached hits too: entries written before the relevance gate
            # (or by a looser config) must not replay false positives.
            return [o for o in cached if is_relevant(mpn, description, o.description)]

        # Hobby distributors list parts by common name, not formal MPN, so try
        # the MPN first and fall back to the description.
        queries: List[str] = []
        for q in (mpn, description):
            q = (q or "").strip()
            if q and q not in queries:
                queries.append(q)

        offers: List[Offer] = []
        for source in self.sources:
            for query in queries:
                try:
                    if source.platform in ("shopify", "shopify_json", "shopify_suggest"):
                        got = self._scrape_shopify(source, query, mpn or query)
                    elif source.platform == "woocommerce_store_api":
                        got = self._scrape_woo_store_api(source, query, mpn or query)
                    else:
                        got = []
                except Exception as exc:  # noqa: BLE001 - one source failing must not break others
                    logger.warning("scrape %s failed: %s", source.name, exc)
                    got = []
                # Drop keyword-search false positives: only keep products that
                # genuinely correspond to the part. An irrelevant hit must not
                # "win" and short-circuit the description fallback query.
                got = [o for o in got if is_relevant(mpn, description, o.description)]
                if got:
                    offers.extend(got)
                    break  # first query that returns relevant hits for this source wins

        set_cached_offers(self.name, cache_key, offers)
        return offers

    # -- rate limiting ------------------------------------------------------
    @staticmethod
    def _throttle(host: str) -> None:
        with _lock:
            now = time.time()
            wait = settings.scrape_min_interval_seconds - (now - _last_hit.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            _last_hit[host] = time.time()

    # -- Shopify search suggest (public keyword search) --------------------
    def _scrape_shopify(self, source: ScrapeSource, query: str, mpn: str) -> List[Offer]:
        self._throttle(source.base_url)
        resp = httpx.get(
            f"{source.base_url}/search/suggest.json",
            params={
                "q": query,
                "resources[type]": "product",
                "resources[limit]": 5,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        products = (
            (((resp.json() or {}).get("resources") or {}).get("results") or {}).get("products")
        ) or []

        offers: List[Offer] = []
        for prod in products:
            offer = self._map_shopify_suggest(source, mpn, prod)
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _map_shopify_suggest(source: ScrapeSource, mpn: str, prod: dict) -> Offer | None:
        raw = str(prod.get("price", "")).replace(",", "")
        cleaned = re.sub(r"[^0-9.]", "", raw)
        try:
            price = float(cleaned)
        except ValueError:
            return None
        if price <= 0:
            return None

        url = prod.get("url", "") or ""
        if url.startswith("/"):
            url = f"{source.base_url}{url.split('?')[0]}"
        return Offer(
            mpn=mpn,
            manufacturer=prod.get("vendor", "") or source.name,
            description=prod.get("title", "") or "",
            distributor=source.name,
            access_method=AccessMethod.scrape,
            authorized=True,
            region=source.region,
            currency=source.currency,
            price_includes_gst=str(source.currency).upper() == "INR",
            price_breaks=[PriceBreak(qty=1, unit_price=round(price, 2))],
            stock=9999 if prod.get("available", True) else 0,
            lead_time_days=source.lead_time_days,
            moq=1,
            product_url=url or source.base_url,
        )

    # -- WooCommerce public Store API --------------------------------------
    def _scrape_woo_store_api(self, source: ScrapeSource, query: str, mpn: str) -> List[Offer]:
        self._throttle(source.base_url)
        resp = httpx.get(
            f"{source.base_url}/wp-json/wc/store/v1/products",
            params={"search": query, "per_page": 5},
            headers={"User-Agent": _USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        products = resp.json() or []

        offers: List[Offer] = []
        for prod in products:
            offer = self._map_woo_product(source, mpn, prod)
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _map_woo_product(source: ScrapeSource, mpn: str, prod: dict) -> Offer | None:
        prices = prod.get("prices") or {}
        raw_price = prices.get("price")
        if raw_price is None:
            return None
        # Store API returns integer strings in the currency's minor units.
        try:
            minor = int(prices.get("currency_minor_unit", 2))
            price = int(raw_price) / (10 ** minor)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        currency = prices.get("currency_code") or source.currency
        return Offer(
            mpn=mpn,
            manufacturer=prod.get("sku", "") or source.name,
            description=prod.get("name", "") or "",
            distributor=source.name,
            access_method=AccessMethod.scrape,
            authorized=True,
            region=source.region,
            currency=currency,
            price_includes_gst=str(currency).upper() == "INR",
            price_breaks=[PriceBreak(qty=1, unit_price=round(price, 2))],
            stock=9999 if prod.get("is_in_stock") else 0,
            lead_time_days=source.lead_time_days,
            moq=1,
            product_url=prod.get("permalink", "") or source.base_url,
        )
