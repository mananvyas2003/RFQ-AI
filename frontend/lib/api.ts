import type { BomLine, Objective, ParseResponse, SourcingResult } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function parseBom(file: File): Promise<ParseResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/bom/parse`, {
    method: "POST",
    body: form,
  });
  return handle<ParseResponse>(res);
}

export async function sourceBom(params: {
  lines: BomLine[];
  destination_country: string;
  objective: Objective;
}): Promise<SourcingResult> {
  const res = await fetch(`${API_BASE}/bom/source`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return handle<SourcingResult>(res);
}

export async function exportBom(params: {
  lines: BomLine[];
  destination_country: string;
  objective: Objective;
}): Promise<Blob> {
  const res = await fetch(`${API_BASE}/bom/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  return res.blob();
}

export { API_BASE };
