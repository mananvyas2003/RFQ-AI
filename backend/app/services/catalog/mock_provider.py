"""Default MVP provider backed by the local mixed-source mock catalog."""
from __future__ import annotations

from typing import List

from app.models import AccessMethod, Offer
from app.services.catalog.base import CatalogProvider
from app.services.catalog.mock_data import get_offers_for_mpn


class MockProvider(CatalogProvider):
    tier = 1
    access_method = AccessMethod.official_api
    enabled = True

    @property
    def name(self) -> str:
        return "mock-catalog"

    def search(self, mpn: str, description: str = "") -> List[Offer]:
        if not mpn:
            return []
        return get_offers_for_mpn(mpn)
