"""Catalog crawler: harvests distributor product catalogs into the local DB.

Pulls the full public catalog from each allow-listed Shopify store
(`/products.json`, paginated) and upserts it into the `scraped_products` table.
BOM lookups then search this table (fast, offline) instead of hitting the live
sites, and this crawler is re-run from time to time to keep prices/stock fresh.

Never touches Nexar - this is only for the consent-listed scrape sources.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List

import httpx
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import ScrapedProduct, SessionLocal
from app.services.catalog.html_catalog import crawl_html_source
from app.services.catalog.stores import scrape_sources

_USER_AGENT = "RFQ-AI/1.0 (+catalog-sync; contact site owner if this is unwanted)"
_PAGE_SIZE = 250
_MAX_PAGES = 100  # safety cap (~25k products/store)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _search_text(product: dict) -> str:
    parts: List[str] = [product.get("title", ""), product.get("vendor", "")]
    parts.extend(product.get("tags", []) or [])
    parts.append(product.get("product_type", "") or "")
    for v in product.get("variants", []) or []:
        parts.append(v.get("sku", "") or "")
        parts.append(v.get("title", "") or "")
    return _norm(" ".join(p for p in parts if p))


def _rows_from_product(source: dict, product: dict) -> ScrapedProduct | None:
    variants = product.get("variants", []) or []
    if not variants:
        return None
    # Prefer the first in-stock variant; fall back to the first one.
    variant = next((v for v in variants if v.get("available")), variants[0])
    try:
        price = float(variant.get("price"))
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    base_url = source["base_url"].rstrip("/")
    handle = product.get("handle", "")
    return ScrapedProduct(
        source=source["name"],
        title=product.get("title", "") or "",
        sku=variant.get("sku", "") or "",
        vendor=product.get("vendor", "") or "",
        price=round(price, 2),
        currency=source.get("currency", "INR"),
        in_stock=any(v.get("available") for v in variants),
        region=source.get("region", "IN"),
        product_url=f"{base_url}/products/{handle}" if handle else base_url,
        search_text=_search_text(product),
    )


def _crawl_shopify(source: dict) -> List[ScrapedProduct]:
    base_url = source["base_url"].rstrip("/")
    rows: List[ScrapedProduct] = []
    with httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=30.0,
                      follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            resp = client.get(
                f"{base_url}/products.json",
                params={"limit": _PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
            products = (resp.json() or {}).get("products", []) or []
            if not products:
                break
            for product in products:
                row = _rows_from_product(source, product)
                if row is not None:
                    rows.append(row)
            if len(products) < _PAGE_SIZE:
                break
            time.sleep(settings.scrape_min_interval_seconds)
    return rows


def _woo_search_text(product: dict) -> str:
    parts: List[str] = [product.get("name", ""), product.get("sku", "")]
    for cat in product.get("categories", []) or []:
        parts.append(cat.get("name", "") or "")
    for tag in product.get("tags", []) or []:
        parts.append(tag.get("name", "") or "")
    return _norm(" ".join(p for p in parts if p))


def _row_from_woo(source: dict, product: dict) -> ScrapedProduct | None:
    prices = product.get("prices") or {}
    raw = prices.get("price")
    if raw is None:
        return None
    try:
        minor = int(prices.get("currency_minor_unit", 2))
        price = int(raw) / (10 ** minor)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    return ScrapedProduct(
        source=source["name"],
        title=product.get("name", "") or "",
        sku=product.get("sku", "") or "",
        vendor=source["name"],
        price=round(price, 2),
        currency=prices.get("currency_code") or source.get("currency", "INR"),
        in_stock=bool(product.get("is_in_stock", True)),
        region=source.get("region", "IN"),
        product_url=product.get("permalink", "") or source["base_url"],
        search_text=_woo_search_text(product),
    )


def _crawl_woocommerce(source: dict) -> List[ScrapedProduct]:
    base_url = source["base_url"].rstrip("/")
    rows: List[ScrapedProduct] = []
    with httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=30.0,
                      follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            resp = client.get(
                f"{base_url}/wp-json/wc/store/v1/products",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            products = resp.json() or []
            if not products:
                break
            for product in products:
                row = _row_from_woo(source, product)
                if row is not None:
                    rows.append(row)
            if len(products) < 100:
                break
            time.sleep(settings.scrape_min_interval_seconds)
    return rows


def _crawl_html_sitemap(source: dict) -> List[ScrapedProduct]:
    """Crawl custom storefronts via public sitemap + product HTML parsing."""
    extracted = crawl_html_source(source)
    rows: List[ScrapedProduct] = []
    for data in extracted:
        title = data.get("title", "") or ""
        sku = data.get("sku", "") or ""
        rows.append(ScrapedProduct(
            source=source["name"],
            title=title,
            sku=sku,
            vendor=data.get("vendor") or source["name"],
            price=round(float(data["price"]), 2),
            currency=source.get("currency", "INR"),
            in_stock=bool(data.get("in_stock", True)),
            region=source.get("region", "IN"),
            product_url=data.get("product_url") or source["base_url"],
            search_text=_norm(" ".join([title, sku, source["name"]])),
        ))
    return rows


def crawl_all(platforms: List[str] | None = None, parallel: int = 1) -> Dict[str, int]:
    """Crawl allow-listed scrape sources and refresh the DB.

    If `platforms` is set (e.g. ["html_sitemap"]), only those platforms are crawled.
    `parallel` > 1 runs that many HTML sources concurrently (different hosts).
    Returns a per-source count of products stored (-1 = failed).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[str, int] = {}
    wanted = {p.lower() for p in platforms} if platforms else None
    sources = []
    for source in scrape_sources():
        platform = source.get("platform", "shopify")
        if wanted is not None and platform.lower() not in wanted:
            continue
        sources.append(source)

    def _run_one(source: dict) -> tuple[str, int]:
        platform = source.get("platform", "shopify")
        try:
            if platform in ("shopify", "shopify_json", "shopify_suggest"):
                rows = _crawl_shopify(source)
            elif platform == "woocommerce_store_api":
                rows = _crawl_woocommerce(source)
            elif platform == "html_sitemap":
                rows = _crawl_html_sitemap(source)
            else:
                return source["name"], 0
        except Exception as exc:  # noqa: BLE001
            print(f"[crawler] {source['name']} failed: {exc}")
            return source["name"], -1

        with SessionLocal() as db:
            if rows or platform != "html_sitemap":
                db.execute(delete(ScrapedProduct).where(ScrapedProduct.source == source["name"]))
                db.add_all(rows)
                db.commit()
        print(f"[crawler] {source['name']}: stored {len(rows)} products")
        return source["name"], len(rows)

    workers = max(1, min(parallel, len(sources) or 1))
    if workers == 1:
        for source in sources:
            name, count = _run_one(source)
            results[name] = count
    else:
        print(f"[crawler] parallel workers={workers}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, s): s["name"] for s in sources}
            for fut in as_completed(futs):
                name, count = fut.result()
                results[name] = count
    return results


def catalog_stats() -> dict:
    """Counts + last-updated per source, for the /catalog/stats endpoint."""
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(ScrapedProduct)) or 0
        rows = db.execute(
            select(
                ScrapedProduct.source,
                func.count(ScrapedProduct.id),
                func.max(ScrapedProduct.updated_at),
            ).group_by(ScrapedProduct.source)
        ).all()
    return {
        "total_products": total,
        "sources": [
            {"source": r[0], "products": r[1], "last_updated": str(r[2])} for r in rows
        ],
    }
