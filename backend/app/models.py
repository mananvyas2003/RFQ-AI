"""Pydantic data models shared across the RFQ-AI backend.

The `Offer` model is deliberately source-agnostic: every provider (Nexar,
Shopify, WooCommerce, mock, scrape) normalizes into this same shape so the
optimizer never needs to know where an offer came from.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AccessMethod(str, Enum):
    """How an offer's data was legally obtained (consent-first policy)."""

    official_api = "official_api"
    shopify = "shopify"
    woocommerce = "woocommerce"
    manual_upload = "manual_upload"
    scrape = "scrape"


class Objective(str, Enum):
    cost = "cost"
    time = "time"


class LineStatus(str, Enum):
    matched = "matched"
    low_confidence = "low_confidence"
    unmatched = "unmatched"


class PriceBreak(BaseModel):
    qty: int
    unit_price: float  # in the offer's native currency


class Offer(BaseModel):
    """A single purchasable offer for a part from one distributor."""

    # Part identity (denormalized onto the offer for self-containment)
    mpn: str
    manufacturer: str
    description: str = ""
    category: str = ""
    hs_code: str = ""

    # Supplier / sourcing metadata
    distributor: str
    access_method: AccessMethod
    authorized: bool = True
    region: str = "IN"  # ISO-2 country the offer ships FROM (used for duty)
    country_of_origin: str = ""  # manufacturing origin (informational)

    currency: str = "INR"
    # Indian retail/scrape/local INR offers are typically GST-inclusive.
    # Imported / foreign-currency offers should set this False.
    price_includes_gst: bool = True
    gst_rate: float = 0.18  # statutory/standard default — verify; override per offer
    price_breaks: List[PriceBreak] = Field(default_factory=list)
    stock: int = 0
    lead_time_days: int = 0
    moq: int = 1
    packaging: str = ""
    product_url: str = ""


class BomLine(BaseModel):
    """One normalized input line from the uploaded BOM."""

    line_no: int
    mpn: str = ""
    manufacturer: str = ""
    quantity: int = 1
    reference: str = ""
    description: str = ""


class DutyBreakdown(BaseModel):
    customs_value_inr: float  # goods value in INR (as priced / FX-converted)
    is_domestic: bool
    hs_code: str = ""
    duty_rate: float = 0.0  # BCD rate applied (0 for domestic)
    duty_amount_inr: float = 0.0  # non-recoverable customs = BCD + SWS
    shipping_inr: float = 0.0
    # CIF cascade (imported); domestic leaves CIF at 0
    assessable_value_cif: float = 0.0
    bcd_amount_inr: float = 0.0
    sws_amount_inr: float = 0.0
    igst_amount_inr: float = 0.0
    # GST (domestic) or IGST (imported) — recoverable via ITC, not rankable
    recoverable_tax_inr: float = 0.0


class SourcedOffer(BaseModel):
    """An `Offer` evaluated for a specific required quantity + destination."""

    offer: Offer
    source_badge: str  # "API" | "Platform" | "Local" | "Scrape"
    purchase_qty: int
    unit_price_inr: float
    line_cost_inr: float
    duty: DutyBreakdown
    landed_cost_inr: float
    effective_lead_time_days: int
    in_stock: bool


class SourcedLine(BaseModel):
    input: BomLine
    status: LineStatus
    matched_mpn: str = ""
    matched_manufacturer: str = ""
    match_confidence: float = 0.0
    chosen: Optional[SourcedOffer] = None
    alternates: List[SourcedOffer] = Field(default_factory=list)


class SourcingSummary(BaseModel):
    currency: str = "INR"
    lines_total: int = 0
    lines_matched: int = 0
    line_coverage: float = 0.0
    total_landed_cost_inr: float = 0.0  # non-recoverable total (ranking basis)
    total_duty_inr: float = 0.0  # non-recoverable customs (BCD + SWS)
    total_recoverable_tax_inr: float = 0.0  # GST/IGST reclaimable via ITC
    max_lead_time_days: int = 0
    local_offers_chosen: int = 0
    imported_offers_chosen: int = 0


class SourcingResult(BaseModel):
    destination_country: str = "IN"
    objective: Objective = Objective.cost
    currency: str = "INR"
    lines: List[SourcedLine] = Field(default_factory=list)
    summary: SourcingSummary = Field(default_factory=SourcingSummary)


# ---- Request / response payloads -------------------------------------------


class ColumnMapping(BaseModel):
    mpn: Optional[str] = None
    manufacturer: Optional[str] = None
    quantity: Optional[str] = None
    reference: Optional[str] = None
    # "Value" (e.g. 10K / 0.1uF) and free-text Description are tracked
    # separately so the parser can merge them instead of picking one.
    value: Optional[str] = None
    description: Optional[str] = None


class ParseResponse(BaseModel):
    headers: List[str] = Field(default_factory=list)
    mapping: ColumnMapping = Field(default_factory=ColumnMapping)
    lines: List[BomLine] = Field(default_factory=list)
    row_count: int = 0


class SourceRequest(BaseModel):
    lines: List[BomLine]
    destination_country: str = "IN"
    objective: Objective = Objective.cost
