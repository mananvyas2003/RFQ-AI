"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { parseBom, sourceBom } from "@/lib/api";
import type { BomLine, Objective, ParseResponse } from "@/lib/types";

const COUNTRIES = [
  { code: "IN", label: "India" },
  { code: "US", label: "United States" },
  { code: "GB", label: "United Kingdom" },
  { code: "DE", label: "Germany" },
];

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [parsed, setParsed] = useState<ParseResponse | null>(null);
  const [lines, setLines] = useState<BomLine[]>([]);
  const [fileName, setFileName] = useState("");
  const [destination, setDestination] = useState("IN");
  const [objective, setObjective] = useState<Objective>("cost");
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const handleFile = useCallback(async (file: File) => {
    setError("");
    setBusy(true);
    // Drop any previous sourcing run so the results page can't show a
    // stale 0%-coverage BOM from an earlier session.
    sessionStorage.removeItem("rfq_result");
    sessionStorage.removeItem("rfq_request");
    try {
      const res = await parseBom(file);
      setParsed(res);
      setLines(res.lines);
      setFileName(file.name);
      if (res.lines.length === 0) {
        setError("No BOM rows were detected in that file.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to parse file.");
    } finally {
      setBusy(false);
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const updateLine = (idx: number, field: keyof BomLine, value: string) => {
    setLines((prev) =>
      prev.map((ln, i) =>
        i === idx
          ? { ...ln, [field]: field === "quantity" ? Math.max(1, Number(value) || 1) : value }
          : ln,
      ),
    );
  };

  const runSourcing = async () => {
    setError("");
    setBusy(true);
    try {
      const result = await sourceBom({ lines, destination_country: destination, objective });
      sessionStorage.setItem("rfq_result", JSON.stringify(result));
      sessionStorage.setItem(
        "rfq_request",
        JSON.stringify({ lines, destination_country: destination }),
      );
      router.push("/results");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to source BOM.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Source a BOM</h1>
        <p className="mt-1 text-slate-600">
          Upload a CSV or Excel BOM. We&apos;ll detect the columns and let you review
          before sourcing.
        </p>
      </div>

      {!parsed && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`card flex cursor-pointer flex-col items-center justify-center gap-3 border-2 border-dashed p-14 text-center transition ${
            dragOver ? "border-brand-500 bg-brand-50" : "border-slate-300"
          }`}
        >
          <div className="grid h-12 w-12 place-items-center rounded-full bg-brand-100 text-2xl text-brand-600">
            +
          </div>
          <p className="text-base font-semibold text-slate-800">
            Drop your BOM here, or click to browse
          </p>
          <p className="text-sm text-slate-500">CSV or XLSX, up to 5 MB</p>
          <a
            href="/sample_bom.csv"
            download
            onClick={(e) => e.stopPropagation()}
            className="mt-2 text-sm font-medium text-brand-600 hover:underline"
          >
            Download a sample BOM
          </a>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
        </div>
      )}

      {busy && !parsed && (
        <p className="text-center text-sm text-slate-500">Parsing {fileName}...</p>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {parsed && (
        <div className="space-y-6">
          <div className="card p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-slate-900">
                  {fileName} - {lines.length} line{lines.length === 1 ? "" : "s"}
                </h2>
                <p className="mt-1 text-sm text-slate-500">Detected columns:</p>
              </div>
              <button
                className="btn-ghost"
                onClick={() => {
                  setParsed(null);
                  setLines([]);
                  setError("");
                }}
              >
                Upload a different file
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {Object.entries(parsed.mapping).map(([field, header]) => (
                <span
                  key={field}
                  className={`badge ${
                    header ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"
                  }`}
                >
                  {field}: {header ?? "not found"}
                </span>
              ))}
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">#</th>
                    <th className="px-4 py-3">Ref</th>
                    <th className="px-4 py-3">MPN</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3 text-right">Qty</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {lines.map((ln, idx) => (
                    <tr key={ln.line_no}>
                      <td className="px-4 py-2 text-slate-400">{ln.line_no}</td>
                      <td className="px-4 py-2 text-slate-600">{ln.reference || "-"}</td>
                      <td className="px-2 py-1">
                        <input
                          value={ln.mpn}
                          onChange={(e) => updateLine(idx, "mpn", e.target.value)}
                          className="w-full rounded-lg border border-transparent px-2 py-1 hover:border-slate-200 focus:border-brand-500 focus:outline-none"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={ln.description}
                          onChange={(e) => updateLine(idx, "description", e.target.value)}
                          className="w-full rounded-lg border border-transparent px-2 py-1 text-slate-600 hover:border-slate-200 focus:border-brand-500 focus:outline-none"
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <input
                          type="number"
                          min={1}
                          value={ln.quantity}
                          onChange={(e) => updateLine(idx, "quantity", e.target.value)}
                          className="w-20 rounded-lg border border-transparent px-2 py-1 text-right hover:border-slate-200 focus:border-brand-500 focus:outline-none"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card flex flex-wrap items-end justify-between gap-6 p-6">
            <div className="flex flex-wrap gap-6">
              <label className="text-sm">
                <span className="mb-1 block font-medium text-slate-700">Ship to</span>
                <select
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                  className="rounded-xl border border-slate-300 px-3 py-2"
                >
                  {COUNTRIES.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="text-sm">
                <span className="mb-1 block font-medium text-slate-700">Optimize for</span>
                <div className="inline-flex rounded-xl border border-slate-300 p-1">
                  {(["cost", "time"] as Objective[]).map((o) => (
                    <button
                      key={o}
                      onClick={() => setObjective(o)}
                      className={`rounded-lg px-4 py-1.5 text-sm font-medium capitalize transition ${
                        objective === o
                          ? "bg-brand-600 text-white"
                          : "text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {o === "cost" ? "Lowest cost" : "Fastest"}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <button className="btn-primary px-6 py-3" disabled={busy || lines.length === 0} onClick={runSourcing}>
              {busy ? "Sourcing..." : "Find best sources"}
            </button>
            <p className="basis-full text-right text-xs text-slate-500">
              Review the rows above, then click <span className="font-medium">Find best sources</span> —
              suppliers are fetched on that step (not on upload).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
