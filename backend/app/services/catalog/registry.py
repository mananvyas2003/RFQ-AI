"""Provider registry implementing the finalized 3-tier sourcing cascade.

Tier 1 (Nexar/official APIs) and Tier 2 (Shopify/WooCommerce platform feeds)
are always queried and their offers merged. Tier 3 (scraping) is only consulted
as a last resort when tiers 1-2 return nothing, and any unauthorized scraped
offers are dropped (consent-first).
"""
from __future__ import annotations

import logging
import re
from typing import List

from app.models import AccessMethod, Offer
from app.services.catalog.base import CatalogProvider
from app.services.catalog.local_catalog_provider import LocalCatalogProvider
from app.services.catalog.mock_provider import MockProvider
from app.services.catalog.nexar_provider import NexarProvider
from app.services.catalog.scrape_provider import ScrapeProvider
from app.services.catalog.shopify_provider import ShopifyProvider
from app.services.catalog.woocommerce_provider import WooCommerceProvider

logger = logging.getLogger(__name__)


def _norm_part(mpn: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (mpn or "").upper())


def _unit_price_at_one(offer: Offer) -> float:
    if not offer.price_breaks:
        return float("inf")
    return min(b.unit_price for b in offer.price_breaks)


class ProviderRegistry:
    def __init__(self, providers: List[CatalogProvider] | None = None) -> None:
        if providers is None:
            nexar = NexarProvider()          # tier 1 (activates with credentials)
            shopify = ShopifyProvider()      # tier 2 (activates with configured stores)
            woo = WooCommerceProvider()      # tier 2 (activates with configured stores)
            local = LocalCatalogProvider()   # tier 2 (crawled scrape catalog, DB)
            scrape = ScrapeProvider()        # tier 3 (live scrape, last-resort fallback)

            mock = MockProvider()            # tier 1 (built-in demo data)
            # Once ANY real source is live (incl. scraping), stop mixing in the
            # demo catalog so results are genuinely real.
            mock.enabled = not (
                nexar.enabled or shopify.enabled or woo.enabled
                or local.enabled or scrape.enabled
            )

            providers = [
                mock,
                nexar,
                shopify,
                woo,
                local,
                scrape,
            ]
        self.providers = providers

    def _providers_at(self, max_tier: int, min_tier: int = 1) -> List[CatalogProvider]:
        return sorted(
            [p for p in self.providers if p.enabled and min_tier <= p.tier <= max_tier],
            key=lambda p: p.tier,
        )

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        offers: List[Offer] = []

        # Tiers 1-2: query and merge.
        for provider in self._providers_at(max_tier=2):
            try:
                offers.extend(provider.search(mpn, description))
            except Exception as exc:  # noqa: BLE001 - one provider must not break sourcing
                logger.warning("provider %s failed for %r: %s", provider.name, mpn, exc)

        # Tier 3: only as a fallback when nothing was found upstream.
        if not offers:
            for provider in self._providers_at(max_tier=3, min_tier=3):
                try:
                    offers.extend(provider.search(mpn, description))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("provider %s failed for %r: %s", provider.name, mpn, exc)

        return self._sanitize(offers)

    @staticmethod
    def _sanitize(offers: List[Offer]) -> List[Offer]:
        """Keep the cheapest offer per (distributor, normalized-part).

        Distinct part identities from the same distributor are preserved;
        casing/punctuation variants of the same MPN collapse to the lowest
        unit price rather than first-wins.
        """
        best: dict[tuple[str, str], Offer] = {}
        for offer in offers:
            # Consent-first: never surface unauthorized scraped data.
            if offer.access_method == AccessMethod.scrape and not offer.authorized:
                continue
            key = (offer.distributor.lower(), _norm_part(offer.mpn))
            prev = best.get(key)
            if prev is None or _unit_price_at_one(offer) < _unit_price_at_one(prev):
                best[key] = offer
        return list(best.values())


# Module-level singleton used by the routes.
registry = ProviderRegistry()
