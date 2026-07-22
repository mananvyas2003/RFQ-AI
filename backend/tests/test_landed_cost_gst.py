"""Landed-cost model for a GST-registered Indian buyer (ITC reclaim).

Ranking must use only NON-RECOVERABLE cost; recoverable GST/IGST is reported
separately and excluded from landed_cost_inr. Symmetric across import vs local.
"""
from __future__ import annotations

import pytest

from app.models import AccessMethod, Offer, PriceBreak
from app.services.duty import compute_duty
from app.services.optimizer import _evaluate


def _imported_offer(
    *,
    hs_code: str = "8541",
    unit_price: float = 1000.0,
    currency: str = "INR",
) -> Offer:
    return Offer(
        mpn="IMP-TEST",
        manufacturer="Test",
        description="imported test part",
        hs_code=hs_code,
        distributor="ForeignDist",
        access_method=AccessMethod.official_api,
        region="US",
        currency=currency,
        price_includes_gst=False,
        price_breaks=[PriceBreak(qty=1, unit_price=unit_price)],
        stock=100,
        lead_time_days=5,
        moq=1,
    )


def _domestic_offer(*, unit_price: float = 1180.0, price_includes_gst: bool = True) -> Offer:
    return Offer(
        mpn="DOM-TEST",
        manufacturer="Test",
        description="domestic test part",
        hs_code="8541",
        distributor="LocalDist",
        access_method=AccessMethod.scrape,
        region="IN",
        currency="INR",
        price_includes_gst=price_includes_gst,
        gst_rate=0.18,
        price_breaks=[PriceBreak(qty=1, unit_price=unit_price)],
        stock=100,
        lead_time_days=2,
        moq=1,
    )


def test_bcd_computed_on_cif_not_goods_alone(monkeypatch):
    """BCD base is CIF = goods + freight + insurance, not goods alone.

    Hand check: goods 1000, freight 200, insurance 11.25 → CIF 1211.25;
    BCD @ 10% = 121.125 → 121.13.
    """
    monkeypatch.setattr("app.services.duty._shipping", lambda *_a, **_k: 200.0)
    # Statutory/standard default insurance when unknown: 1.125% of goods.
    monkeypatch.setattr(
        "app.services.duty.DEFAULT_INSURANCE_RATE", 0.01125, raising=False
    )

    duty = compute_duty(_imported_offer(hs_code="8541"), "IN", customs_value_inr=1000.0)

    assert duty.assessable_value_cif == pytest.approx(1211.25)
    assert duty.bcd_amount_inr == pytest.approx(121.13, abs=0.01)
    # Must NOT be 10% of goods alone (100.0).
    assert duty.bcd_amount_inr != pytest.approx(100.0)


def test_sws_is_ten_percent_of_bcd(monkeypatch):
    monkeypatch.setattr("app.services.duty._shipping", lambda *_a, **_k: 200.0)
    monkeypatch.setattr(
        "app.services.duty.DEFAULT_INSURANCE_RATE", 0.01125, raising=False
    )

    duty = compute_duty(_imported_offer(hs_code="8541"), "IN", customs_value_inr=1000.0)

    assert duty.sws_amount_inr == pytest.approx(0.10 * duty.bcd_amount_inr, abs=0.01)


def test_igst_on_cif_plus_bcd_plus_sws_excluded_from_landed(monkeypatch):
    """IGST = rate * (CIF + BCD + SWS); recoverable, not in landed_cost_inr."""
    monkeypatch.setattr("app.services.duty._shipping", lambda *_a, **_k: 200.0)
    monkeypatch.setattr(
        "app.services.duty.DEFAULT_INSURANCE_RATE", 0.01125, raising=False
    )

    offer = _imported_offer(hs_code="8541")
    duty = compute_duty(offer, "IN", customs_value_inr=1000.0)

    cif = duty.assessable_value_cif
    bcd = duty.bcd_amount_inr
    sws = duty.sws_amount_inr
    expected_igst = 0.18 * (cif + bcd + sws)

    assert duty.igst_amount_inr == pytest.approx(expected_igst, abs=0.02)
    assert duty.recoverable_tax_inr == pytest.approx(duty.igst_amount_inr, abs=0.02)
    # Non-recoverable customs total
    assert duty.duty_amount_inr == pytest.approx(bcd + sws, abs=0.02)

    evaluated = _evaluate(offer, required_qty=1, destination_country="IN")
    # Rankable landed = CIF + BCD + SWS (IGST excluded)
    assert evaluated.landed_cost_inr == pytest.approx(cif + bcd + sws, abs=0.02)
    assert abs(evaluated.landed_cost_inr - (cif + bcd + sws + duty.igst_amount_inr)) > 1.0
    assert evaluated.duty.recoverable_tax_inr == pytest.approx(expected_igst, abs=0.02)


def test_domestic_gst_inclusive_is_degrossed():
    """1180 INR inclusive @ 18% → net 1000 in landed, 180 recoverable."""
    offer = _domestic_offer(unit_price=1180.0, price_includes_gst=True)
    evaluated = _evaluate(offer, required_qty=1, destination_country="IN")

    # Free domestic shipping above 1000 on the offer price.
    assert evaluated.duty.shipping_inr == 0.0
    assert evaluated.landed_cost_inr == pytest.approx(1000.0)
    assert evaluated.duty.recoverable_tax_inr == pytest.approx(180.0)
    assert evaluated.duty.duty_amount_inr == 0.0
    assert evaluated.duty.is_domestic is True


def test_neutrality_import_vs_domestic_same_non_recoverable(monkeypatch):
    """Same true non-recoverable cost → equal landed_cost_inr (no tax bias)."""
    monkeypatch.setattr("app.services.duty._shipping", lambda is_dom, *_a, **_k: 0.0)
    monkeypatch.setattr("app.services.duty.DEFAULT_INSURANCE_RATE", 0.0, raising=False)

    # Domestic: 1180 inclusive @ 18% → net 1000 + shipping 0 = 1000
    domestic = _evaluate(
        _domestic_offer(unit_price=1180.0, price_includes_gst=True),
        required_qty=1,
        destination_country="IN",
    )

    # Import: goods 1000, freight 0, insurance 0, BCD 0 (HS 8542) → landed 1000
    # IGST still accrues but must not affect ranking.
    imported = _evaluate(
        _imported_offer(hs_code="8542", unit_price=1000.0),
        required_qty=1,
        destination_country="IN",
    )

    assert domestic.landed_cost_inr == pytest.approx(imported.landed_cost_inr, abs=0.02)
    assert domestic.duty.recoverable_tax_inr == pytest.approx(180.0)
    assert imported.duty.recoverable_tax_inr > 0.0  # IGST present but excluded
    assert imported.duty.duty_amount_inr == pytest.approx(0.0)


def test_domestic_still_zero_customs_duty():
    duty = compute_duty(_domestic_offer(), "IN", customs_value_inr=1180.0)
    assert duty.is_domestic is True
    assert duty.duty_rate == 0.0
    assert duty.duty_amount_inr == 0.0
    assert duty.bcd_amount_inr == 0.0
    assert duty.sws_amount_inr == 0.0


def test_unknown_destination_still_uses_conservative_bcd_default(monkeypatch):
    monkeypatch.setattr("app.services.duty._shipping", lambda *_a, **_k: 0.0)
    monkeypatch.setattr("app.services.duty.DEFAULT_INSURANCE_RATE", 0.0, raising=False)

    duty = compute_duty(_imported_offer(hs_code="9999"), "ZZ", customs_value_inr=1000.0)
    assert duty.is_domestic is False
    assert duty.duty_rate == 0.10  # conservative BCD default
    assert duty.bcd_amount_inr == pytest.approx(100.0)
    assert duty.sws_amount_inr == pytest.approx(10.0)
    assert duty.duty_amount_inr == pytest.approx(110.0)
