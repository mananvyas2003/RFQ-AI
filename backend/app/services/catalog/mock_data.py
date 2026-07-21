"""Loads and caches the mock catalog JSON and exposes it as normalized data.

Shared by the fuzzy matcher (needs part identities) and the mock provider
(needs offers). Real providers would replace this with live API calls.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List

from app.models import AccessMethod, Offer, PriceBreak

_DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "mock_catalog.json"


@lru_cache(maxsize=1)
def _raw() -> dict:
    with _DATA_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_parts() -> List[dict]:
    """Return raw part dicts (mpn, manufacturer, description, aliases, ...)."""
    return _raw().get("parts", [])


@lru_cache(maxsize=1)
def _offer_index() -> dict[str, List[Offer]]:
    index: dict[str, List[Offer]] = {}
    for part in get_parts():
        offers: List[Offer] = []
        for raw in part.get("offers", []):
            offers.append(
                Offer(
                    mpn=part["mpn"],
                    manufacturer=part["manufacturer"],
                    description=part.get("description", ""),
                    category=part.get("category", ""),
                    hs_code=part.get("hs_code", ""),
                    distributor=raw["distributor"],
                    access_method=AccessMethod(raw["access_method"]),
                    authorized=raw.get("authorized", True),
                    region=raw.get("region", "IN"),
                    country_of_origin=raw.get("country_of_origin", ""),
                    currency=raw.get("currency", "INR"),
                    price_breaks=[PriceBreak(**pb) for pb in raw.get("price_breaks", [])],
                    stock=raw.get("stock", 0),
                    lead_time_days=raw.get("lead_time_days", 0),
                    moq=raw.get("moq", 1),
                    packaging=raw.get("packaging", ""),
                    product_url=raw.get("product_url", ""),
                )
            )
        index[part["mpn"].upper()] = offers
    return index


def get_offers_for_mpn(mpn: str) -> List[Offer]:
    return list(_offer_index().get(mpn.upper(), []))
