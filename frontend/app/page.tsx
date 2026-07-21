import Link from "next/link";

const features = [
  {
    title: "Fuzzy part matching",
    body: "Messy or partial MPNs and description-only lines are normalized to real manufacturer parts with a confidence score.",
  },
  {
    title: "Global + local sourcing",
    body: "Offers aggregated across global distributors and Indian suppliers, ranked neutrally on true cost.",
  },
  {
    title: "Landed cost with duty",
    body: "Compares on price + shipping + import duty, so a cheap import that attracts duty can lose to a local part.",
  },
  {
    title: "Cost or time optimized",
    body: "Switch objectives to minimize spend or lead time. Alternates shown for every line.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-16">
      <section className="text-center">
        <span className="badge bg-brand-50 text-brand-700">
          For hardware engineers &amp; companies - B2B &amp; B2C
        </span>
        <h1 className="mx-auto mt-5 max-w-3xl text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
          Upload your PCB BOM. Get back a{" "}
          <span className="text-brand-600">cost- and time-optimized</span> sourced
          BOM.
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
          RFQ-AI parses your Bill of Materials, matches every part globally, and
          returns the best supplier per line - accounting for price breaks, stock,
          lead time, and import duty. India-first, priced in INR.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link href="/upload" className="btn-primary px-6 py-3 text-base">
            Source a BOM
          </Link>
          <a href="/sample_bom.csv" download className="btn-ghost px-6 py-3 text-base">
            Download sample BOM
          </a>
        </div>
      </section>

      <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {features.map((f) => (
          <div key={f.title} className="card p-6">
            <h3 className="text-base font-semibold text-slate-900">{f.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">{f.body}</p>
          </div>
        ))}
      </section>

      <section className="card p-8">
        <h2 className="text-xl font-bold text-slate-900">How it works</h2>
        <ol className="mt-6 grid gap-6 sm:grid-cols-3">
          {[
            ["1", "Upload", "Drop a CSV/XLSX BOM. Columns are auto-detected; adjust the mapping if needed."],
            ["2", "Match & search", "Each line is matched to a real part and priced across all available suppliers."],
            ["3", "Optimize", "Get the best supplier per line by cost or time, with duty-aware landed cost and alternates."],
          ].map(([n, title, body]) => (
            <li key={n} className="flex gap-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-600 font-bold text-white">
                {n}
              </span>
              <div>
                <p className="font-semibold text-slate-900">{title}</p>
                <p className="mt-1 text-sm text-slate-600">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
