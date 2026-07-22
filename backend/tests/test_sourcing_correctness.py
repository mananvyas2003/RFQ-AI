"""Failing-then-passing correctness tests for BOM sourcing.

These pin the identity/confidence/price-break/dedup/duty/parser bugs fixed
in the correctness pass. Prefer mock-only registry so live catalogs cannot
mask the mock-catalog alias seam.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models import (
    AccessMethod,
    BomLine,
    LineStatus,
    Objective,
    Offer,
    PriceBreak,
    SourceRequest,
)
from app.services.catalog.registry import ProviderRegistry
from app.services.duty import compute_duty
from app.services.optimizer import _evaluate, source_bom, source_line
from app.services.parser import parse_bom


# ---------------------------------------------------------------------------
# Identity seam: alias MPN must still produce a chosen offer
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mock_only_registry")
def test_alias_mpn_ne555_produces_chosen_offer():
    line = BomLine(line_no=1, mpn="NE555", quantity=1, description="555 timer")
    result = source_line(line, "IN", Objective.cost)
    assert result.chosen is not None, (
        "NE555 matched the mock catalog as NE555P but produced no offer "
        "(alias→exact lookup seam)"
    )
    assert result.chosen.landed_cost_inr > 0
    assert result.status != LineStatus.unmatched


@pytest.mark.usefixtures("mock_only_registry")
def test_alias_mpn_lm358_produces_chosen_offer():
    line = BomLine(line_no=1, mpn="lm358", quantity=2, description="dual op-amp")
    result = source_line(line, "IN", Objective.cost)
    assert result.chosen is not None, (
        "lm358 matched the mock catalog as LM358DR but produced no offer "
        "(alias→exact lookup seam)"
    )
    assert result.chosen.landed_cost_inr > 0
    assert result.status != LineStatus.unmatched


# ---------------------------------------------------------------------------
# Confidence must never contradict status
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mock_only_registry")
def test_unmatched_never_reports_100_confidence():
    line = BomLine(line_no=1, mpn="ZZZ-NOT-A-REAL-PART-99999", quantity=1)
    result = source_line(line, "IN", Objective.cost)
    assert result.status == LineStatus.unmatched
    assert result.chosen is None
    assert result.match_confidence < 100.0


@pytest.mark.usefixtures("mock_only_registry")
def test_no_hardcoded_90_confidence_without_real_match():
    """Live-offer fallback must not invent a 90.0 confidence."""
    # A part the mock catalog does not know; with mock-only, no offers either.
    line = BomLine(line_no=1, mpn="ESP32-WROOM-32E-UNIQUE", quantity=1, description="")
    result = source_line(line, "IN", Objective.cost)
    assert result.match_confidence != 90.0
    if result.status == LineStatus.unmatched:
        assert result.match_confidence < 70.0 or result.match_confidence == 0.0


@pytest.mark.usefixtures("mock_only_registry")
def test_alias_miss_does_not_report_unmatched_at_100():
    """The NE555 bug: matched@100% then unmatched because offers missed."""
    line = BomLine(line_no=1, mpn="NE555", quantity=1)
    result = source_line(line, "IN", Objective.cost)
    if result.status == LineStatus.unmatched:
        pytest.fail(
            f"NE555 reported unmatched with confidence={result.match_confidence}; "
            "a catalog match must keep status matched/low_confidence and find offers"
        )
    assert result.match_confidence == 100.0
    assert result.chosen is not None


# ---------------------------------------------------------------------------
# Duty: assert current behavior (do not change rates)
# ---------------------------------------------------------------------------

def _offer(*, region: str, hs_code: str = "8542") -> Offer:
    return Offer(
        mpn="TEST-MPN",
        manufacturer="Test",
        description="test",
        hs_code=hs_code,
        distributor="TestDist",
        access_method=AccessMethod.official_api,
        region=region,
        currency="INR",
        price_breaks=[PriceBreak(qty=1, unit_price=100.0)],
        stock=100,
        lead_time_days=3,
        moq=1,
    )


def test_duty_domestic_is_zero():
    duty = compute_duty(_offer(region="IN"), "IN", customs_value_inr=500.0)
    assert duty.is_domestic is True
    assert duty.duty_rate == 0.0
    assert duty.duty_amount_inr == 0.0


def test_duty_imported_is_nonzero():
    # HS 8541 currently has a 10% rate for IN; 8542 is 0% in the table.
    duty = compute_duty(_offer(region="US", hs_code="8541"), "IN", customs_value_inr=500.0)
    assert duty.is_domestic is False
    assert duty.duty_rate > 0.0
    assert duty.duty_amount_inr > 0.0


def test_duty_unknown_destination_uses_conservative_default():
    duty = compute_duty(_offer(region="US"), "ZZ", customs_value_inr=1000.0)
    assert duty.is_domestic is False
    assert duty.duty_rate == 0.10  # conservative BCD default in duty.py
    # BCD is on CIF (goods + freight + insurance), not goods alone.
    assert duty.assessable_value_cif > 1000.0
    assert duty.bcd_amount_inr == pytest.approx(0.10 * duty.assessable_value_cif, abs=0.02)
    assert duty.sws_amount_inr == pytest.approx(0.10 * duty.bcd_amount_inr, abs=0.02)
    assert duty.duty_amount_inr == pytest.approx(
        duty.bcd_amount_inr + duty.sws_amount_inr, abs=0.02
    )


# ---------------------------------------------------------------------------
# Price breaks: round purchase qty up when it lowers total landed cost
# ---------------------------------------------------------------------------

def test_price_break_rounds_up_when_cheaper_total():
    # Required 5 @ 100/ea = 500; break at 10 @ 40/ea = 400 → must buy 10.
    offer = Offer(
        mpn="BREAK-PART",
        manufacturer="Test",
        description="price break part",
        hs_code="8542",
        distributor="LocalDist",
        access_method=AccessMethod.shopify,
        region="IN",
        currency="INR",
        price_breaks=[
            PriceBreak(qty=1, unit_price=100.0),
            PriceBreak(qty=10, unit_price=40.0),
        ],
        stock=1000,
        lead_time_days=2,
        moq=1,
    )
    evaluated = _evaluate(offer, required_qty=5, destination_country="IN")
    assert evaluated.purchase_qty == 10, (
        f"expected round-up to break qty 10, got {evaluated.purchase_qty}"
    )
    assert evaluated.line_cost_inr == pytest.approx(400.0)


def test_price_break_does_not_round_up_when_more_expensive():
    # Required 5 @ 10/ea = 50; break at 100 @ 9/ea = 900 → stay at 5.
    offer = Offer(
        mpn="BREAK-PART-2",
        manufacturer="Test",
        description="price break part",
        hs_code="8542",
        distributor="LocalDist",
        access_method=AccessMethod.shopify,
        region="IN",
        currency="INR",
        price_breaks=[
            PriceBreak(qty=1, unit_price=10.0),
            PriceBreak(qty=100, unit_price=9.0),
        ],
        stock=1000,
        lead_time_days=2,
        moq=1,
    )
    evaluated = _evaluate(offer, required_qty=5, destination_country="IN")
    assert evaluated.purchase_qty == 5
    assert evaluated.line_cost_inr == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Dedup: cheapest per (distributor, normalized-part); distinct parts kept
# ---------------------------------------------------------------------------

def test_sanitize_keeps_cheapest_per_distributor_and_normalized_part():
    cheap = Offer(
        mpn="NE555P",
        manufacturer="TI",
        description="timer",
        distributor="Digi-Key",
        access_method=AccessMethod.official_api,
        region="US",
        currency="USD",
        price_breaks=[PriceBreak(qty=1, unit_price=0.20)],
        stock=10,
        lead_time_days=4,
        moq=1,
    )
    expensive = Offer(
        mpn="ne555p",  # same identity, different casing
        manufacturer="TI",
        description="timer",
        distributor="Digi-Key",
        access_method=AccessMethod.official_api,
        region="US",
        currency="USD",
        price_breaks=[PriceBreak(qty=1, unit_price=0.90)],
        stock=10,
        lead_time_days=4,
        moq=1,
    )
    # First-wins today would keep expensive if it arrives first.
    cleaned = ProviderRegistry._sanitize([expensive, cheap])
    assert len(cleaned) == 1
    assert cleaned[0].price_breaks[0].unit_price == 0.20


def test_sanitize_keeps_distinct_parts_from_same_distributor():
    a = Offer(
        mpn="NE555P",
        manufacturer="TI",
        description="timer",
        distributor="Digi-Key",
        access_method=AccessMethod.official_api,
        region="US",
        currency="USD",
        price_breaks=[PriceBreak(qty=1, unit_price=0.50)],
        stock=10,
        lead_time_days=4,
        moq=1,
    )
    b = Offer(
        mpn="LM358DR",
        manufacturer="TI",
        description="opamp",
        distributor="Digi-Key",
        access_method=AccessMethod.official_api,
        region="US",
        currency="USD",
        price_breaks=[PriceBreak(qty=1, unit_price=0.30)],
        stock=10,
        lead_time_days=4,
        moq=1,
    )
    cleaned = ProviderRegistry._sanitize([a, b])
    mpns = {o.mpn.upper() for o in cleaned}
    assert mpns == {"NE555P", "LM358DR"}


# ---------------------------------------------------------------------------
# Parser: Value + Description merged; sample headers detected
# ---------------------------------------------------------------------------

def test_parser_merges_value_and_description_columns():
    csv = (
        b"Reference,Qty,Value,MPN,Manufacturer,Description\n"
        b"R1,10,10K,RC0603FR-0710KL,Yageo,Resistor 0603\n"
    )
    parsed = parse_bom("test.csv", csv)
    assert parsed.mapping.value == "Value"
    assert parsed.mapping.description == "Description"
    assert len(parsed.lines) == 1
    desc = parsed.lines[0].description
    assert "10K" in desc
    assert "Resistor" in desc or "0603" in desc


def test_parser_maps_sample_bom_headers():
    path = Path(__file__).resolve().parents[1] / "sample_bom.csv"
    parsed = parse_bom("sample_bom.csv", path.read_bytes())
    m = parsed.mapping
    assert m.mpn == "MPN"
    assert m.manufacturer == "Manufacturer"
    assert m.quantity == "Qty"
    assert m.reference == "Reference"
    assert m.value == "Value"
    assert m.description == "Description"
    assert parsed.row_count == 10


@pytest.mark.usefixtures("mock_only_registry")
def test_sample_bom_mock_only_coverage_is_complete():
    path = Path(__file__).resolve().parents[1] / "sample_bom.csv"
    parsed = parse_bom("sample_bom.csv", path.read_bytes())
    result = source_bom(
        SourceRequest(lines=parsed.lines, destination_country="IN", objective=Objective.cost)
    )
    assert result.summary.lines_matched == 10, (
        f"expected 10/10 with mock catalog, got "
        f"{result.summary.lines_matched}/{result.summary.lines_total}: "
        + ", ".join(
            f"{(ln.input.mpn or ln.input.description)}={ln.status.value}"
            for ln in result.lines
            if ln.chosen is None
        )
    )
