"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { sourceBom } from "@/lib/api";
import { inr, leadLabel, pct } from "@/lib/format";
import type { BomLine, Objective, SourcedLine, SourcedOffer, SourcingResult } from "@/lib/types";

interface StoredRequest {
  lines: BomLine[];
  destination_country: string;
}

const BADGE_STYLES: Record<string, string> = {
  Local: "bg-emerald-50 text-emerald-700",
  API: "bg-indigo-50 text-indigo-700",
  Platform: "bg-sky-50 text-sky-700",
  Scrape: "bg-slate-100 text-slate-500",
};

function statusBadge(status: string) {
  if (status === "matched") return "bg-emerald-50 text-emerald-700";
  if (status === "low_confidence") return "bg-amber-50 text-amber-700";
  return "bg-red-50 text-red-700";
}

function OfferRow({ o, highlight }: { o: SourcedOffer; highlight?: boolean }) {
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm ${
        highlight ? "bg-brand-50" : "bg-slate-50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`badge ${BADGE_STYLES[o.source_badge] ?? "bg-slate-100"}`}>
          {o.source_badge}
        </span>
        <span className="font-medium text-slate-800">{o.offer.distributor}</span>
        <span className="text-slate-400">
          ({o.offer.region}{o.offer.country_of_origin ? ` - origin ${o.offer.country_of_origin}` : ""})
        </span>
        {!o.in_stock && (
          <span className="badge bg-amber-50 text-amber-700">backorder</span>
        )}
      </div>
      <div className="flex items-center gap-5 text-right">
        <span className="text-slate-500">
          {inr(o.unit_price_inr)} x {o.purchase_qty}
        </span>
        <span className="text-slate-500">{leadLabel(o.effective_lead_time_days)}</span>
        <span className="text-slate-500">
          duty {o.duty.is_domestic ? "-" : inr(o.duty.duty_amount_inr)}
        </span>
        <span className="w-24 font-semibold text-slate-900">{inr(o.landed_cost_inr)}</span>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

export default function ResultsPage() {
  const [result, setResult] = useState<SourcingResult | null>(null);
  const [request, setRequest] = useState<StoredRequest | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const r = sessionStorage.getItem("rfq_result");
    const q = sessionStorage.getItem("rfq_request");
    if (r) setResult(JSON.parse(r));
    if (q) setRequest(JSON.parse(q));
  }, []);

  const rerun = async (objective: Objective) => {
    if (!request || busy) return;
    setBusy(true);
    try {
      const res = await sourceBom({ ...request, objective });
      setResult(res);
      sessionStorage.setItem("rfq_result", JSON.stringify(res));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (n: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(n) ? next.delete(n) : next.add(n);
      return next;
    });

  if (!result) {
    return (
      <div className="card p-12 text-center">
        <h1 className="text-xl font-bold text-slate-900">No results yet</h1>
        <p className="mt-2 text-slate-600">Upload a BOM to get an optimized sourcing plan.</p>
        <Link href="/upload" className="btn-primary mt-6 px-6 py-3">
          Source a BOM
        </Link>
      </div>
    );
  }

  const s = result.summary;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Optimized sourced BOM</h1>
          <p className="mt-1 text-slate-600">
            Shipping to {result.destination_country} - optimized for{" "}
            <span className="font-medium capitalize">{result.objective}</span>. Prices in INR.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-xl border border-slate-300 p-1">
            {(["cost", "time"] as Objective[]).map((o) => (
              <button
                key={o}
                onClick={() => rerun(o)}
                disabled={busy}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
                  result.objective === o
                    ? "bg-brand-600 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {o === "cost" ? "Lowest cost" : "Fastest"}
              </button>
            ))}
          </div>
          <Link href="/upload" className="btn-ghost">
            New BOM
          </Link>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          label="Total landed cost"
          value={inr(s.total_landed_cost_inr)}
          sub={`${s.imported_offers_chosen} imported - ${s.local_offers_chosen} local`}
        />
        <SummaryCard label="Max lead time" value={leadLabel(s.max_lead_time_days)} />
        <SummaryCard label="Total import duty" value={inr(s.total_duty_inr)} />
        <SummaryCard
          label="Line coverage"
          value={pct(s.line_coverage)}
          sub={`${s.lines_matched} of ${s.lines_total} lines matched`}
        />
      </section>

      <section className="space-y-3">
        {result.lines.map((line: SourcedLine) => {
          const isOpen = expanded.has(line.input.line_no);
          return (
            <div key={line.input.line_no} className="card overflow-hidden">
              <button
                onClick={() => line.chosen && toggle(line.input.line_no)}
                className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-4 text-left"
              >
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <span className="text-sm text-slate-400">#{line.input.line_no}</span>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900">
                      {line.matched_mpn || line.input.mpn || line.input.description || "Unknown part"}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      {line.input.reference && <span>{line.input.reference} - </span>}
                      qty {line.input.quantity}
                      {line.matched_manufacturer && <span> - {line.matched_manufacturer}</span>}
                    </p>
                  </div>
                  <span className={`badge ${statusBadge(line.status)}`}>
                    {line.status === "matched"
                      ? `${line.match_confidence}% match`
                      : line.status === "low_confidence"
                        ? `${line.match_confidence}% - review`
                        : "no match"}
                  </span>
                </div>

                {line.chosen ? (
                  <div className="flex items-center gap-4 text-sm">
                    <span className={`badge ${BADGE_STYLES[line.chosen.source_badge] ?? "bg-slate-100"}`}>
                      {line.chosen.source_badge}
                    </span>
                    <span className="hidden text-slate-600 sm:inline">
                      {line.chosen.offer.distributor}
                    </span>
                    <span className="text-slate-500">
                      {leadLabel(line.chosen.effective_lead_time_days)}
                    </span>
                    <span className="w-24 text-right font-semibold text-slate-900">
                      {inr(line.chosen.landed_cost_inr)}
                    </span>
                    <span className="text-slate-400">{isOpen ? "-" : "+"}</span>
                  </div>
                ) : (
                  <span className="text-sm text-red-500">No offers found</span>
                )}
              </button>

              {isOpen && line.chosen && (
                <div className="space-y-2 border-t border-slate-100 bg-white px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Chosen
                  </p>
                  <OfferRow o={line.chosen} highlight />
                  {line.alternates.length > 0 && (
                    <>
                      <p className="pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Alternates
                      </p>
                      {line.alternates.map((alt, i) => (
                        <OfferRow key={i} o={alt} />
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
