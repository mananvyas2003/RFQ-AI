import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "RFQ-AI | AI BOM Sourcing",
  description:
    "Upload a PCB BOM and get back a cost- or time-optimized, duty-aware sourced BOM.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">
                R
              </span>
              <span className="text-lg font-bold tracking-tight">
                RFQ<span className="text-brand-600">-AI</span>
              </span>
            </Link>
            <nav className="flex items-center gap-6 text-sm font-medium text-slate-600">
              <Link href="/" className="hover:text-slate-900">
                Home
              </Link>
              <Link href="/upload" className="btn-primary !py-2">
                Source a BOM
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 py-10 text-center text-xs text-slate-400">
          RFQ-AI MVP - India-first BOM sourcing. Prices in INR. Duty figures are
          representative, not legally binding.
        </footer>
      </body>
    </html>
  );
}
