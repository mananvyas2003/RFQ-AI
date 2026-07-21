"""CatalogProvider interface.

Every data source (Nexar, Shopify, WooCommerce, mock, scrape) implements this
same contract and returns normalized `Offer` objects, so the optimizer is fully
decoupled from where data comes from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from app.models import AccessMethod, Offer


class CatalogProvider(ABC):
    #: Tier in the sourcing cascade (lower runs first). Nexar=1, platforms=2, scrape=3.
    tier: int = 100

    #: Which access method this provider represents (drives consent enforcement).
    access_method: AccessMethod = AccessMethod.official_api

    #: A provider may be globally disabled (e.g. scraping is off by default).
    enabled: bool = True

    @property
    @abstractmethod
    def name(self) -> str:  # pragma: no cover - trivial
        ...

    @abstractmethod
    def search(self, mpn: str, description: str = "") -> List[Offer]:
        """Return all offers this source has for the given part.

        Implementations should return an empty list (never raise) when they have
        no data for the part so the registry can fall through to the next tier.
        """
        ...
