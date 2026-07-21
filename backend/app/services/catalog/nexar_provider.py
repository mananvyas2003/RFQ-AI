"""Tier-1 Nexar / Octopart adapter (real implementation).

Activates automatically when NEXAR_CLIENT_ID / NEXAR_CLIENT_SECRET are set.
Uses OAuth2 client-credentials to get a bearer token, then runs the GraphQL
`supSearchMpn` query and normalizes seller offers into our `Offer` shape.

Results are cached in the DB (see `services/cache.py`) because every part Nexar
returns counts against your account's part limit.
"""
from __future__ import annotations

import time
from typing import List, Optional

import httpx

from app.config import settings
from app.models import AccessMethod, Offer, PriceBreak
from app.services.cache import get_cached_offers, set_cached_offers
from app.services.catalog.base import CatalogProvider

_SEARCH_QUERY = """
query SearchMpn($q: String!, $limit: Int!, $country: String!) {
  supSearchMpn(q: $q, limit: $limit, country: $country) {
    results {
      part {
        mpn
        shortDescription
        manufacturer { name }
        category { name }
        sellers(authorizedOnly: false) {
          company { name }
          isAuthorized
          offers {
            inventoryLevel
            moq
            packaging
            factoryLeadDays
            clickUrl
            prices { quantity price currency }
          }
        }
      }
    }
  }
}
""".strip()


class NexarProvider(CatalogProvider):
    tier = 1
    access_method = AccessMethod.official_api

    def __init__(self) -> None:
        self.enabled = settings.nexar_enabled
        self._token: str = ""
        self._token_expiry: float = 0.0

    @property
    def name(self) -> str:
        return "nexar"

    # -- auth ---------------------------------------------------------------
    def _get_token(self) -> str:
        # Reuse the token until ~60s before it expires.
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = httpx.post(
            settings.nexar_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.nexar_client_id,
                "client_secret": settings.nexar_client_secret,
                "scope": "supply.domain",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 86400))
        return self._token

    # -- search -------------------------------------------------------------
    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not self.enabled or not mpn:
            return []

        cached = get_cached_offers(self.name, mpn)
        if cached is not None:
            return cached

        try:
            offers = self._query(mpn)
        except Exception:  # noqa: BLE001 - never break sourcing on a source error
            return []

        set_cached_offers(self.name, mpn, offers)
        return offers

    def _query(self, mpn: str) -> List[Offer]:
        resp = httpx.post(
            settings.nexar_api_url,
            json={
                "query": _SEARCH_QUERY,
                "variables": {
                    "q": mpn,
                    "limit": settings.nexar_limit,
                    "country": settings.nexar_ship_to,
                },
            },
            headers={"Authorization": f"Bearer {self._get_token()}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        body = resp.json()
        results = (
            (body.get("data") or {}).get("supSearchMpn") or {}
        ).get("results") or []
        return self._map_results(results)

    @staticmethod
    def _map_results(results: list) -> List[Offer]:
        offers: List[Offer] = []
        for res in results:
            part = res.get("part") or {}
            part_mpn = part.get("mpn", "")
            manufacturer = ((part.get("manufacturer") or {}).get("name")) or ""
            description = part.get("shortDescription", "") or ""
            category = ((part.get("category") or {}).get("name")) or ""
            for seller in part.get("sellers") or []:
                distributor = ((seller.get("company") or {}).get("name")) or "Unknown"
                authorized = bool(seller.get("isAuthorized", False))
                for raw in seller.get("offers") or []:
                    offer = NexarProvider._map_offer(
                        part_mpn, manufacturer, description, category,
                        distributor, authorized, raw,
                    )
                    if offer is not None:
                        offers.append(offer)
        return offers

    @staticmethod
    def _map_offer(
        mpn: str, manufacturer: str, description: str, category: str,
        distributor: str, authorized: bool, raw: dict,
    ) -> Optional[Offer]:
        prices = raw.get("prices") or []
        breaks: List[PriceBreak] = []
        currency = "USD"
        for p in prices:
            qty = p.get("quantity")
            price = p.get("price")
            if qty is None or price is None:
                continue
            currency = p.get("currency") or currency
            breaks.append(PriceBreak(qty=int(qty), unit_price=float(price)))
        if not breaks:
            return None
        # Nexar offers are global distributors; treat as imported (region unknown)
        # unless the offer is priced in INR, in which case it ships within India.
        region = "IN" if currency.upper() == "INR" else ""
        return Offer(
            mpn=mpn,
            manufacturer=manufacturer,
            description=description,
            category=category,
            distributor=distributor,
            access_method=AccessMethod.official_api,
            authorized=authorized,
            region=region,
            currency=currency.upper(),
            price_breaks=breaks,
            stock=int(raw.get("inventoryLevel") or 0),
            lead_time_days=int(raw.get("factoryLeadDays") or 0),
            moq=int(raw.get("moq") or 1),
            packaging=raw.get("packaging") or "",
            product_url=raw.get("clickUrl") or "",
        )
