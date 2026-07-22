"""Sourcing optimizer: turns matched parts + offers into an optimized BOM.

Ranks offers on true landed cost (price + shipping + duty), so a cheaper
import that attracts duty can lose to a local Indian offer. Supports two
objectives: cost (minimize landed cost) and time (minimize lead time).
Ranking is neutral - no affiliate bias.
"""
from __future__ import annotations

from typing import List

from app.models import (
    BomLine,
    LineStatus,
    Objective,
    Offer,
    SourceRequest,
    SourcedLine,
    SourcedOffer,
    SourcingResult,
    SourcingSummary,
)
from app.services.catalog.registry import registry
from app.services.duty import compute_duty
from app.services.fx import to_inr
from app.services.matcher import match_line

_MAX_ALTERNATES = 4
_BACKORDER_PENALTY_DAYS = 30


def _norm_mpn(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _applicable_unit_price(offer: Offer, purchase_qty: int) -> float:
    """Native-currency unit price for the given quantity, honoring price breaks."""
    if not offer.price_breaks:
        return 0.0
    breaks = sorted(offer.price_breaks, key=lambda b: b.qty)
    unit = breaks[0].unit_price
    for b in breaks:
        if purchase_qty >= b.qty:
            unit = b.unit_price
        else:
            break
    return unit


def _source_badge(offer: Offer, destination_country: str) -> str:
    if offer.region.upper() == destination_country.upper():
        return "Local"
    if offer.access_method.value in ("shopify", "woocommerce"):
        return "Platform"
    if offer.access_method.value == "scrape":
        return "Scrape"
    return "API"


def _evaluate(offer: Offer, required_qty: int, destination_country: str) -> SourcedOffer:
    purchase_qty = max(required_qty, offer.moq)
    unit_native = _applicable_unit_price(offer, purchase_qty)
    unit_inr = to_inr(unit_native, offer.currency)
    line_cost_inr = unit_inr * purchase_qty

    duty = compute_duty(offer, destination_country, line_cost_inr)
    landed = line_cost_inr + duty.duty_amount_inr + duty.shipping_inr

    in_stock = offer.stock >= purchase_qty
    effective_lead = offer.lead_time_days + (0 if in_stock else _BACKORDER_PENALTY_DAYS)

    return SourcedOffer(
        offer=offer,
        source_badge=_source_badge(offer, destination_country),
        purchase_qty=purchase_qty,
        unit_price_inr=round(unit_inr, 4),
        line_cost_inr=round(line_cost_inr, 2),
        duty=duty,
        landed_cost_inr=round(landed, 2),
        effective_lead_time_days=effective_lead,
        in_stock=in_stock,
    )


def _sort_key(objective: Objective):
    if objective == Objective.time:
        return lambda s: (s.effective_lead_time_days, s.landed_cost_inr)
    return lambda s: (s.landed_cost_inr, s.effective_lead_time_days)


def source_line(line: BomLine, destination_country: str, objective: Objective) -> SourcedLine:
    match = match_line(line)

    # Prefer the user's raw MPN. The mock-catalog matcher is only a fallback
    # for description-only lines (no MPN on the BOM) — never rewrite a real
    # user-supplied MPN to a demo-catalog alias, which would miss live stock.
    raw_mpn = (line.mpn or "").strip()
    search_mpn = raw_mpn or (match.mpn if match.part is not None else "")
    search_desc = (line.description or "").strip()

    if not search_mpn and not search_desc:
        # Nothing usable to look up anywhere.
        return SourcedLine(input=line, status=LineStatus.unmatched, match_confidence=match.confidence)

    offers = registry.search(search_mpn, search_desc)

    if match.part is not None and raw_mpn and _norm_mpn(raw_mpn) == _norm_mpn(match.mpn):
        # User MPN agreed with the local catalog identity.
        matched_mpn = match.mpn
        matched_manufacturer = match.manufacturer
        confidence = match.confidence
        status = match.status
    elif match.part is not None and not raw_mpn:
        # Description-only line resolved via the local catalog.
        matched_mpn = match.mpn
        matched_manufacturer = match.manufacturer
        confidence = match.confidence
        status = match.status
    elif offers:
        # A live source recognised this part even though it isn't in the local
        # catalog. Trust the source's identity for it.
        matched_mpn = offers[0].mpn or raw_mpn or search_mpn
        matched_manufacturer = offers[0].manufacturer
        confidence = match.confidence if match.confidence else 90.0
        status = LineStatus.matched
    else:
        # Nothing local and no live source had it.
        return SourcedLine(input=line, status=LineStatus.unmatched, match_confidence=match.confidence)

    if not offers:
        return SourcedLine(
            input=line,
            status=status,
            matched_mpn=matched_mpn,
            matched_manufacturer=matched_manufacturer,
            match_confidence=confidence,
        )

    required_qty = max(1, line.quantity)
    evaluated = [_evaluate(o, required_qty, destination_country) for o in offers]
    evaluated.sort(key=_sort_key(objective))

    return SourcedLine(
        input=line,
        status=status,
        matched_mpn=matched_mpn,
        matched_manufacturer=matched_manufacturer,
        match_confidence=confidence,
        chosen=evaluated[0],
        alternates=evaluated[1 : 1 + _MAX_ALTERNATES],
    )


def source_bom(request: SourceRequest) -> SourcingResult:
    lines: List[SourcedLine] = [
        source_line(line, request.destination_country, request.objective)
        for line in request.lines
    ]

    matched = [ln for ln in lines if ln.chosen is not None]
    total_landed = sum(ln.chosen.landed_cost_inr for ln in matched)
    total_duty = sum(ln.chosen.duty.duty_amount_inr for ln in matched)
    max_lead = max((ln.chosen.effective_lead_time_days for ln in matched), default=0)
    local = sum(1 for ln in matched if ln.chosen.duty.is_domestic)
    imported = len(matched) - local

    summary = SourcingSummary(
        lines_total=len(lines),
        lines_matched=len(matched),
        line_coverage=round(len(matched) / len(lines), 3) if lines else 0.0,
        total_landed_cost_inr=round(total_landed, 2),
        total_duty_inr=round(total_duty, 2),
        max_lead_time_days=max_lead,
        local_offers_chosen=local,
        imported_offers_chosen=imported,
    )

    return SourcingResult(
        destination_country=request.destination_country,
        objective=request.objective,
        lines=lines,
        summary=summary,
    )
