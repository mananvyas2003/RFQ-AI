"""Import-duty + shipping + landed-cost engine.

Duty is calculated (not looked up live) from destination country + HS code +
where the offer ships from. Domestic offers (ships from the destination
country) incur zero import duty - the India-first advantage the optimizer
surfaces.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import DutyBreakdown, Offer

_DUTY_FILE = Path(__file__).resolve().parents[1] / "data" / "duty_table.json"

# Representative shipping estimates (INR).
_DOMESTIC_FLAT = 40.0
_DOMESTIC_FREE_ABOVE = 1000.0
_INTL_FLAT = 700.0
_INTL_PERCENT = 0.02


@lru_cache(maxsize=1)
def _duty_table() -> dict:
    with _DUTY_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _duty_rate(destination: str, hs_code: str) -> float:
    table = _duty_table().get(destination.upper())
    if not table:
        # Unknown destination: assume a conservative default.
        return 0.10
    hs4 = (hs_code or "")[:4]
    if hs4 and hs4 in table:
        return float(table[hs4])
    return float(table.get("default", 0.0))


def _shipping(is_domestic: bool, customs_value_inr: float) -> float:
    if is_domestic:
        return 0.0 if customs_value_inr >= _DOMESTIC_FREE_ABOVE else _DOMESTIC_FLAT
    return _INTL_FLAT + _INTL_PERCENT * customs_value_inr


def compute_duty(offer: Offer, destination_country: str, customs_value_inr: float) -> DutyBreakdown:
    """customs_value_inr is the goods value (unit_price * qty) already in INR."""
    is_domestic = offer.region.upper() == destination_country.upper()
    shipping = _shipping(is_domestic, customs_value_inr)

    if is_domestic:
        return DutyBreakdown(
            customs_value_inr=round(customs_value_inr, 2),
            is_domestic=True,
            hs_code=offer.hs_code,
            duty_rate=0.0,
            duty_amount_inr=0.0,
            shipping_inr=round(shipping, 2),
        )

    rate = _duty_rate(destination_country, offer.hs_code)
    duty_amount = rate * customs_value_inr
    return DutyBreakdown(
        customs_value_inr=round(customs_value_inr, 2),
        is_domestic=False,
        hs_code=offer.hs_code,
        duty_rate=rate,
        duty_amount_inr=round(duty_amount, 2),
        shipping_inr=round(shipping, 2),
    )
