"""Tier-2 Shopify platform adapter (real implementation).

One reusable provider serves many Shopify-based distributors (e.g. Robocraze).
Each store is configured in `STORES_CONFIG` with its base URL + an Admin API
access token the merchant issues (custom app). Consent-first: only configured
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
from app.services.catalog.stores import shopify_stores

logger = logging.getLogger(__name__)
_ADMIN_API_VERSION = "2024-10"

_PRODUCT_QUERY = """
query ($q: String!) {
  products(first: 5, query: $q) {
    edges {
      node {
        title
        onlineStoreUrl
        variants(first: 1) {
          edges {
            node {
              price
              inventoryQuantity
            }
          }
        }
      }
    }
  }
}
""".strip()


class ShopifyStore:
    def __init__(self, name: str, base_url: str, access_token: str, region: str = "IN",
                 currency: str = "INR") -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.region = region
        self.currency = currency


class ShopifyProvider(CatalogProvider):
    tier = 2
    access_method = AccessMethod.shopify

    def __init__(self, stores: List[ShopifyStore] | None = None) -> None:
        if stores is None:
            stores = [ShopifyStore(**s) for s in shopify_stores()]
        self.stores = stores
        self.enabled = bool(self.stores)

    @property
    def name(self) -> str:
        return "shopify"

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
                logger.warning("shopify store %s failed: %s", store.name, exc)
                continue

        # Keyword search returns loosely-related products; keep only genuine
        # matches so a wrong item becomes an honest "no match".
        offers = [o for o in offers if is_relevant(mpn, description, o.description)]
        set_cached_offers(self.name, mpn, offers)
        return offers

    def _search_store(self, store: ShopifyStore, mpn: str) -> List[Offer]:
        resp = httpx.post(
            f"{store.base_url}/admin/api/{_ADMIN_API_VERSION}/graphql.json",
            json={"query": _PRODUCT_QUERY, "variables": {"q": mpn}},
            headers={
                "X-Shopify-Access-Token": store.access_token,
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        body = resp.json()
        edges = (((body.get("data") or {}).get("products") or {}).get("edges")) or []
        offers: List[Offer] = []
        for edge in edges:
            offer = self._map_product(store, mpn, edge.get("node") or {})
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _map_product(store: ShopifyStore, mpn: str, node: dict) -> Offer | None:
        variants = ((node.get("variants") or {}).get("edges")) or []
        if not variants:
            return None
        variant = variants[0].get("node") or {}
        try:
            price = float(variant.get("price"))
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        stock = variant.get("inventoryQuantity")
        stock = int(stock) if stock is not None else 0

        return Offer(
            mpn=mpn,
            manufacturer=store.name,
            description=node.get("title", "") or "",
            distributor=store.name,
            access_method=AccessMethod.shopify,
            authorized=True,
            region=store.region,
            currency=store.currency,
            price_includes_gst=str(store.currency).upper() == "INR",
            price_breaks=[PriceBreak(qty=1, unit_price=price)],
            stock=stock,
            lead_time_days=4,
            moq=1,
            product_url=node.get("onlineStoreUrl", "") or "",
        )
