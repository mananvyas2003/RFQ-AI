"""Sourcing optimizer: turns matched parts + offers into an optimized BOM.

Ranks offers on true non-recoverable landed cost (CIF + BCD + SWS for imports;
GST-exclusive net + shipping for domestic). Recoverable GST/IGST is reported
separately and excluded from ranking so buy-local vs import is not tax-biased.
Supports two objectives: cost (minimize landed cost) and time (minimize lead
time). Ranking is neutral - no affiliate bias.
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
    """Pick purchase qty = max(required, moq), or round up to a price break
    when that lowers total landed cost.
    """
    base_qty = max(required_qty, offer.moq)
    candidate_qtys = {base_qty}
    for brk in offer.price_breaks:
        if brk.qty > base_qty:
            candidate_qtys.add(brk.qty)

    best: SourcedOffer | None = None
    for purchase_qty in candidate_qtys:
        unit_native = _applicable_unit_price(offer, purchase_qty)
        unit_inr = to_inr(unit_native, offer.currency)
        line_cost_inr = unit_inr * purchase_qty

        duty = compute_duty(offer, destination_country, line_cost_inr)
        if duty.is_domestic:
            # GST-inclusive prices are de-grossed; only net + shipping ranks.
            net_goods = duty.customs_value_inr - duty.recoverable_tax_inr
            landed = net_goods + duty.shipping_inr
        else:
            # CIF already includes freight + insurance; add non-recoverable BCD+SWS.
            # IGST (recoverable_tax_inr) is excluded from ranking.
            landed = duty.assessable_value_cif + duty.duty_amount_inr

        in_stock = offer.stock >= purchase_qty
        effective_lead = offer.lead_time_days + (0 if in_stock else _BACKORDER_PENALTY_DAYS)

        candidate = SourcedOffer(
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
        if best is None or candidate.landed_cost_inr < best.landed_cost_inr:
            best = candidate

    assert best is not None  # candidate_qtys is never empty
    return best


def _sort_key(objective: Objective):
    if objective == Objective.time:
        return lambda s: (s.effective_lead_time_days, s.landed_cost_inr)
    return lambda s: (s.landed_cost_inr, s.effective_lead_time_days)


def source_line(line: BomLine, destination_country: str, objective: Objective) -> SourcedLine:
    match = match_line(line)

    # Prefer the user's raw MPN for live APIs, but ALWAYS also try the matched
    # canonical MPN. The mock catalog keys offers by canonical identity
    # (NE555P / LM358DR); searching only the raw alias ("NE555" / "lm358")
    # misses those offers and incorrectly reports unmatched @ 100% confidence.
    raw_mpn = (line.mpn or "").strip()
    canonical_mpn = match.mpn if match.part is not None else ""
    search_desc = (line.description or "").strip()

    search_keys: List[str] = []
    for key in (raw_mpn, canonical_mpn):
        if key and key not in search_keys:
            search_keys.append(key)
    if not search_keys and search_desc:
        search_keys.append("")  # description-only lookup

    if not search_keys:
        return SourcedLine(
            input=line,
            status=LineStatus.unmatched,
            match_confidence=match.confidence,
        )

    offers: List[Offer] = []
    for key in search_keys:
        offers.extend(registry.search(key, search_desc))
    # Re-sanitize across merged query results (each search already sanitized).
    offers = registry._sanitize(offers)

    if match.part is not None:
        # Catalog identity wins; never demote a real match to unmatched just
        # because the raw string missed an offer key.
        matched_mpn = match.mpn
        matched_manufacturer = match.manufacturer
        confidence = match.confidence
        status = match.status
    elif offers:
        matched_mpn = offers[0].mpn or raw_mpn
        matched_manufacturer = offers[0].manufacturer
        # Honest confidence: reflect the matcher, never invent a 90.0 default.
        confidence = match.confidence
        status = LineStatus.matched
    else:
        return SourcedLine(
            input=line,
            status=LineStatus.unmatched,
            match_confidence=match.confidence,
        )

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
    total_recoverable = sum(ln.chosen.duty.recoverable_tax_inr for ln in matched)
    max_lead = max((ln.chosen.effective_lead_time_days for ln in matched), default=0)
    local = sum(1 for ln in matched if ln.chosen.duty.is_domestic)
    imported = len(matched) - local

    summary = SourcingSummary(
        lines_total=len(lines),
        lines_matched=len(matched),
        line_coverage=round(len(matched) / len(lines), 3) if lines else 0.0,
        total_landed_cost_inr=round(total_landed, 2),
        total_duty_inr=round(total_duty, 2),
        total_recoverable_tax_inr=round(total_recoverable, 2),
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
