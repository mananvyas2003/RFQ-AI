"""Refresh the local scrape catalog from the allow-listed distributor sites.

Run manually, or schedule it (e.g. Windows Task Scheduler / cron) to keep prices
and stock current:

    python crawl.py
    python crawl.py --platform html_sitemap   # only custom HTML sites
    python crawl.py --platform shopify,woocommerce_store_api

It crawls every allow-listed source in the "scrape" section of STORES_CONFIG and
upserts their products into the database. Nexar is never crawled.
"""
from __future__ import annotations

import argparse
import sys

from app.db import init_db
from app.services.catalog.crawler import catalog_stats, crawl_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl distributor catalogs into the local DB")
    parser.add_argument(
        "--platform",
        default="",
        help="Comma-separated platforms to crawl (shopify, woocommerce_store_api, html_sitemap). "
             "Default: all configured sources.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Crawl this many sources concurrently (useful for html_sitemap across hosts).",
    )
    args = parser.parse_args()
    platforms = [p.strip() for p in args.platform.split(",") if p.strip()] or None

    init_db()
    print("Crawling allow-listed distributor catalogs...")
    if platforms:
        print(f"  filter platforms: {platforms}")
    results = crawl_all(platforms=platforms, parallel=max(1, args.parallel))
    if not results:
        print("No matching scrape sources configured (check stores.json + SCRAPE_ENABLED).")
        sys.exit(1)
    for source, count in results.items():
        status = "FAILED" if count < 0 else f"{count} products"
        print(f"  - {source}: {status}")
    print("\nCatalog now holds:")
    stats = catalog_stats()
    print(f"  total: {stats['total_products']} products")
    for s in stats["sources"]:
        print(f"  - {s['source']}: {s['products']} (updated {s['last_updated']})")


if __name__ == "__main__":
    main()
