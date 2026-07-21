"""Quick end-to-end smoke test of parse -> source using the sample BOM."""
from pathlib import Path

from app.models import Objective, SourceRequest
from app.services.optimizer import source_bom
from app.services.parser import parse_bom


def main() -> None:
    content = Path("sample_bom.csv").read_bytes()
    parsed = parse_bom("sample_bom.csv", content)
    print("Detected mapping:", parsed.mapping.model_dump())
    print("Parsed lines:", parsed.row_count)

    for objective in (Objective.cost, Objective.time):
        result = source_bom(
            SourceRequest(lines=parsed.lines, destination_country="IN", objective=objective)
        )
        s = result.summary
        print(f"\n=== objective={objective.value} ===")
        print(
            f"coverage={s.lines_matched}/{s.lines_total} "
            f"total_landed=INR {s.total_landed_cost_inr} "
            f"duty=INR {s.total_duty_inr} max_lead={s.max_lead_time_days}d "
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
                    f"lead={o.effective_lead_time_days}d"
                )
            else:
                print(
                    f"  L{ln.input.line_no} {ln.input.mpn or ln.input.description!r} "
                    f"-> {ln.status.value} ({ln.match_confidence}%)"
                )


if __name__ == "__main__":
    main()
