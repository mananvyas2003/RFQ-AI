export type Objective = "cost" | "time";
export type LineStatus = "matched" | "low_confidence" | "unmatched";

export interface PriceBreak {
  qty: number;
  unit_price: number;
}

export interface Offer {
  mpn: string;
  manufacturer: string;
  description: string;
  category: string;
  hs_code: string;
  distributor: string;
  access_method: string;
  authorized: boolean;
  region: string;
  country_of_origin: string;
  currency: string;
  price_includes_gst: boolean;
  gst_rate: number;
  price_breaks: PriceBreak[];
  stock: number;
  lead_time_days: number;
  moq: number;
  packaging: string;
  product_url: string;
}

export interface DutyBreakdown {
  customs_value_inr: number;
  is_domestic: boolean;
  hs_code: string;
  duty_rate: number;
  duty_amount_inr: number;
  shipping_inr: number;
  assessable_value_cif: number;
  bcd_amount_inr: number;
  sws_amount_inr: number;
  igst_amount_inr: number;
  recoverable_tax_inr: number;
}

export interface SourcedOffer {
  offer: Offer;
  source_badge: string;
  purchase_qty: number;
  unit_price_inr: number;
  line_cost_inr: number;
  duty: DutyBreakdown;
  landed_cost_inr: number;
  effective_lead_time_days: number;
  in_stock: boolean;
}

export interface BomLine {
  line_no: number;
  mpn: string;
  manufacturer: string;
  quantity: number;
  reference: string;
  description: string;
}

export interface SourcedLine {
  input: BomLine;
  status: LineStatus;
  matched_mpn: string;
  matched_manufacturer: string;
  match_confidence: number;
  chosen: SourcedOffer | null;
  alternates: SourcedOffer[];
}

export interface SourcingSummary {
  currency: string;
  lines_total: number;
  lines_matched: number;
  line_coverage: number;
  total_landed_cost_inr: number;
  total_duty_inr: number;
  total_recoverable_tax_inr: number;
  max_lead_time_days: number;
  local_offers_chosen: number;
  imported_offers_chosen: number;
}

export interface SourcingResult {
  destination_country: string;
  objective: Objective;
  currency: string;
  lines: SourcedLine[];
  summary: SourcingSummary;
}

export interface ColumnMapping {
  mpn: string | null;
  manufacturer: string | null;
  quantity: string | null;
  reference: string | null;
  value: string | null;
  description: string | null;
}

export interface ParseResponse {
  headers: string[];
  mapping: ColumnMapping;
  lines: BomLine[];
  row_count: number;
}
