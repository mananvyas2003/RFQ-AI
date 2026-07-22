"""Import-duty + shipping + landed-cost engine.

For a GST-registered Indian buyer, ranking uses only NON-RECOVERABLE cost:
  Imported: CIF (goods + freight + insurance) + BCD + SWS; IGST is recoverable.
  Domestic: GST-exclusive net + domestic shipping; embedded GST is recoverable.

Domestic offers (ships from the destination country) incur zero import duty.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models import DutyBreakdown, Offer

_DUTY_FILE = Path(__file__).resolve().parents[1] / "data" / "duty_table.json"

# Representative shipping estimates (INR).
_DOMESTIC_FLAT = 40.0
_DOMESTIC_FREE_ABOVE = 1000.0
_INTL_FLAT = 700.0
_INTL_PERCENT = 0.02

# Statutory/standard default — verify against CBIC tariff; override per HS.
DEFAULT_SWS_RATE = 0.10
# Statutory/standard default — verify against CBIC tariff; override per HS.
DEFAULT_IGST_RATE = 0.18
# Standard customs assumption when actual insurance is unknown; overridable.
DEFAULT_INSURANCE_RATE = 0.01125

_META_KEYS = {"_README", "_note"}


@lru_cache(maxsize=1)
def _duty_table() -> dict:
    with _DUTY_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_rate_entry(raw: Any) -> dict[str, float]:
    """Accept legacy bare BCD float or {bcd, igst, sws, aidc} object."""
    if isinstance(raw, dict):
        return {
            "bcd": float(raw.get("bcd", 0.0)),
            "igst": float(raw.get("igst", DEFAULT_IGST_RATE)),
            "sws": float(raw.get("sws", DEFAULT_SWS_RATE)),
            "aidc": float(raw.get("aidc", 0.0)),
        }
    # Legacy single-number entry = BCD only
    return {
        "bcd": float(raw),
        "igst": DEFAULT_IGST_RATE,
        "sws": DEFAULT_SWS_RATE,
        "aidc": 0.0,
    }


def _rate_entry(destination: str, hs_code: str) -> dict[str, float]:
    table = _duty_table().get(destination.upper())
    if not table:
        # Unknown destination: conservative BCD default + statutory SWS/IGST.
        return {
            "bcd": 0.10,
            "igst": DEFAULT_IGST_RATE,
            "sws": DEFAULT_SWS_RATE,
            "aidc": 0.0,
        }
    hs4 = (hs_code or "")[:4]
    if hs4 and hs4 in table and hs4 not in _META_KEYS:
        return _normalize_rate_entry(table[hs4])
    if "default" in table:
        return _normalize_rate_entry(table["default"])
    return {
        "bcd": 0.0,
        "igst": DEFAULT_IGST_RATE,
        "sws": DEFAULT_SWS_RATE,
        "aidc": 0.0,
    }


def _shipping(is_domestic: bool, customs_value_inr: float) -> float:
    if is_domestic:
        return 0.0 if customs_value_inr >= _DOMESTIC_FREE_ABOVE else _DOMESTIC_FLAT
    return _INTL_FLAT + _INTL_PERCENT * customs_value_inr


def compute_duty(offer: Offer, destination_country: str, customs_value_inr: float) -> DutyBreakdown:
    """customs_value_inr is the goods value (unit_price * qty) already in INR."""
    is_domestic = offer.region.upper() == destination_country.upper()
    shipping = _shipping(is_domestic, customs_value_inr)
    goods = float(customs_value_inr)

    if is_domestic:
        if offer.price_includes_gst and offer.gst_rate > 0:
            net = goods / (1.0 + offer.gst_rate)
            recoverable = goods - net
        else:
            net = goods
            recoverable = 0.0
        # Rankable domestic base is GST-exclusive net; shipping stays additive.
        # Store net in assessable_value_cif-equivalent slot? Keep CIF at 0;
        # optimizer uses customs_value_inr (goods as priced) + recoverable to derive net.
        return DutyBreakdown(
            customs_value_inr=round(goods, 2),
            is_domestic=True,
            hs_code=offer.hs_code,
            duty_rate=0.0,
            duty_amount_inr=0.0,
            shipping_inr=round(shipping, 2),
            assessable_value_cif=0.0,
            bcd_amount_inr=0.0,
            sws_amount_inr=0.0,
            igst_amount_inr=0.0,
            recoverable_tax_inr=round(recoverable, 2),
        )

    rates = _rate_entry(destination_country, offer.hs_code)
    bcd_rate = rates["bcd"]
    sws_rate = rates["sws"]
    igst_rate = rates["igst"]

    insurance = DEFAULT_INSURANCE_RATE * goods
    cif = goods + shipping + insurance
    bcd = bcd_rate * cif
    sws = sws_rate * bcd
    igst = igst_rate * (cif + bcd + sws)
    duty_non_recoverable = bcd + sws

    return DutyBreakdown(
        customs_value_inr=round(goods, 2),
        is_domestic=False,
        hs_code=offer.hs_code,
        duty_rate=bcd_rate,
        duty_amount_inr=round(duty_non_recoverable, 2),
        shipping_inr=round(shipping, 2),
        assessable_value_cif=round(cif, 2),
        bcd_amount_inr=round(bcd, 2),
        sws_amount_inr=round(sws, 2),
        igst_amount_inr=round(igst, 2),
        recoverable_tax_inr=round(igst, 2),
    )
