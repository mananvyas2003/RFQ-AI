"""Quick end-to-end smoke test of parse -> source using the sample BOM."""
from pathlib import Path

from app.models import Objective, SourceRequest
from app.services.optimizer import source_bom
from app.services.parser import parse_bom


def _print_worked_example(label: str, chosen) -> None:
    """Print every intermediate for one imported and one domestic line."""
    d = chosen.duty
    goods = d.customs_value_inr
    print(f"\n--- worked example: {label} ---")
    if d.is_domestic:
        net = goods - d.recoverable_tax_inr
        print(f"  goods_gross={goods}")
        print(f"  gst_rate={chosen.offer.gst_rate} price_includes_gst={chosen.offer.price_includes_gst}")
        print(f"  net={net}")
        print(f"  recoverable_tax(GST)={d.recoverable_tax_inr}")
        print(f"  shipping={d.shipping_inr}")
        print(f"  landed_cost_inr(non-recoverable)={chosen.landed_cost_inr}")
        print(f"  BCD/SWS/IGST=0 (domestic)")
    else:
        print(f"  goods={goods}")
        print(f"  freight(shipping)={d.shipping_inr}")
        insurance = round(d.assessable_value_cif - goods - d.shipping_inr, 2)
        print(f"  insurance={insurance}")
        print(f"  CIF={d.assessable_value_cif}")
        print(f"  BCD_rate={d.duty_rate} BCD={d.bcd_amount_inr}")
        print(f"  SWS={d.sws_amount_inr}")
        print(f"  IGST={d.igst_amount_inr} (recoverable)")
        print(f"  duty_amount(BCD+SWS)={d.duty_amount_inr}")
        print(f"  landed_cost_inr(non-recoverable)=CIF+BCD+SWS={chosen.landed_cost_inr}")
        print(f"  recoverable_tax_inr={d.recoverable_tax_inr}")


def main() -> None:
    content = Path("sample_bom.csv").read_bytes()
    parsed = parse_bom("sample_bom.csv", content)
    print("Detected mapping:", parsed.mapping.model_dump())
    print("Parsed lines:", parsed.row_count)

    printed_domestic = False
    printed_imported = False

    for objective in (Objective.cost, Objective.time):
        result = source_bom(
            SourceRequest(lines=parsed.lines, destination_country="IN", objective=objective)
        )
        s = result.summary
        print(f"\n=== objective={objective.value} ===")
        print(
            f"coverage={s.lines_matched}/{s.lines_total} "
            f"total_landed(non-recoverable)=INR {s.total_landed_cost_inr} "
            f"duty(BCD+SWS)=INR {s.total_duty_inr} "
            f"recoverable_tax=INR {s.total_recoverable_tax_inr} "
            f"max_lead={s.max_lead_time_days}d "
            f"local={s.local_offers_chosen} imported={s.imported_offers_chosen}"
        )
        for ln in result.lines:
            if ln.chosen:
                o = ln.chosen
                print(
                    f"  L{ln.input.line_no} {ln.input.mpn or ln.input.description!r} "
                    f"-> {ln.matched_mpn} ({ln.match_confidence}%) "
                    f"[{o.source_badge}] {o.offer.distributor} "
                    f"qty{o.purchase_qty} landed=INR {o.landed_cost_inr} "
                    f"recoverable=INR {o.duty.recoverable_tax_inr} "
                    f"lead={o.effective_lead_time_days}d"
                )
                if objective == Objective.cost:
                    if o.duty.is_domestic and not printed_domestic:
                        _print_worked_example("domestic", o)
                        printed_domestic = True
                    if (not o.duty.is_domestic) and not printed_imported:
                        _print_worked_example("imported", o)
                        printed_imported = True
            else:
                print(
                    f"  L{ln.input.line_no} {ln.input.mpn or ln.input.description!r} "
                    f"-> {ln.status.value} ({ln.match_confidence}%)"
                )


if __name__ == "__main__":
    main()
