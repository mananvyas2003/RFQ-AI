"""Tier-2 WooCommerce platform adapter (real implementation).

One reusable provider serves many WooCommerce distributors (e.g. Robu.in,
Sunrom). Each store is configured in `STORES_CONFIG` with its base URL + REST
consumer key/secret issued by the merchant. Consent-first: only configured
stores are queried.
"""
from __future__ import annotations

import logging
from typing import List

import httpx

from app.models import AccessMethod, Offer, PriceBreak
from app.services.cache import get_cached_offers, set_cached_offers
from app.services.catalog.base import CatalogProvider
from app.services.catalog.relevance import is_relevant
from app.services.catalog.stores import woocommerce_stores

logger = logging.getLogger(__name__)


class WooStore:
    def __init__(self, name: str, base_url: str, consumer_key: str, consumer_secret: str,
                 region: str = "IN", currency: str = "INR") -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.region = region
        self.currency = currency


class WooCommerceProvider(CatalogProvider):
    tier = 2
    access_method = AccessMethod.woocommerce

    def __init__(self, stores: List[WooStore] | None = None) -> None:
        if stores is None:
            stores = [WooStore(**s) for s in woocommerce_stores()]
        self.stores = stores
        self.enabled = bool(self.stores)

    @property
    def name(self) -> str:
        return "woocommerce"

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not self.enabled or not mpn:
            return []

        cached = get_cached_offers(self.name, mpn)
        if cached is not None:
            return [o for o in cached if is_relevant(mpn, description, o.description)]

        offers: List[Offer] = []
        for store in self.stores:
            try:
                offers.extend(self._search_store(store, mpn))
            except Exception as exc:  # noqa: BLE001 - one store failing must not break others
                logger.warning("woocommerce store %s failed: %s", store.name, exc)
                continue

        # Keyword search returns loosely-related products; keep only genuine
        # matches so a wrong item becomes an honest "no match".
        offers = [o for o in offers if is_relevant(mpn, description, o.description)]
        set_cached_offers(self.name, mpn, offers)
        return offers

    def _search_store(self, store: WooStore, mpn: str) -> List[Offer]:
        resp = httpx.get(
            f"{store.base_url}/wp-json/wc/v3/products",
            params={"search": mpn, "per_page": 5},
            auth=(store.consumer_key, store.consumer_secret),
            timeout=20.0,
        )
        resp.raise_for_status()
        products = resp.json() or []
        offers: List[Offer] = []
        for prod in products:
            offer = self._map_product(store, mpn, prod)
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _map_product(store: WooStore, mpn: str, prod: dict) -> Offer | None:
        price_str = prod.get("price") or prod.get("regular_price") or ""
        try:
            price = float(price_str)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        stock_qty = prod.get("stock_quantity")
        if stock_qty is None:
            stock_qty = 9999 if prod.get("stock_status") == "instock" else 0

        return Offer(
            mpn=mpn,
            manufacturer=store.name,
            description=prod.get("name", "") or "",
            distributor=store.name,
            access_method=AccessMethod.woocommerce,
            authorized=True,
            region=store.region,
            currency=store.currency,
            price_includes_gst=str(store.currency).upper() == "INR",
            price_breaks=[PriceBreak(qty=1, unit_price=price)],
            stock=int(stock_qty),
            lead_time_days=3,
            moq=1,
            product_url=prod.get("permalink", "") or "",
        )
