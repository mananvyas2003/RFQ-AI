"""HTML catalog helpers: sitemap discovery + product-page extraction.

Used for Indian distributors that are not Shopify/WooCommerce (OpenCart,
custom CMS, etc.). Reads public sitemaps and product HTML (JSON-LD / Open Graph
/ common price markers) — no headless browser, no Cloudflare bypass.
"""
from __future__ import annotations

import gzip
import io
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings

_USER_AGENT = "RFQ-AI/1.0 (+catalog-sync; contact site owner if this is unwanted)"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Default: skip obvious non-product paths.
_DEFAULT_SKIP = re.compile(
    r"(?i)(/cart|/checkout|/account|/login|/register|/blog|/tag/|"
    r"/manufacturer|/brand/|/search|/contact|/wishlist|/compare|"
    r"\.(?:jpg|jpeg|png|gif|pdf|css|js|xml|gz)(?:$|\?))"
)

# Per-source product-URL allow patterns (matched against full URL).
_URL_ALLOW: Dict[str, re.Pattern[str]] = {
    "Sunrom": re.compile(r"/p/[^/?#]+", re.I),
    "Rhydolabz": re.compile(r"rhydolabz\.com/[^/?#]+$", re.I),
    "ElectronicsComp": re.compile(r"electronicscomp\.com/[a-z0-9][^/?#]*$", re.I),
    "Robokits": re.compile(r"robokits\.co\.in/.+/.+", re.I),
    "DNATech": re.compile(r"dnatechindia\.com/.+\.html$", re.I),
    "ElectronicsSpices": re.compile(r"/product/[^/?#]+", re.I),
    "NexRobotics": re.compile(r"nex-robotics\.com/.+", re.I),
    "Mifratech": re.compile(r"mifratech\.com/.+", re.I),
    "Probots": re.compile(r"probots\.in/.+", re.I),
    "Semikart": re.compile(r"/product/.+", re.I),
    "KitsnSpares": re.compile(r"kitsnspares\.com/.+", re.I),
    "FlyRobo": re.compile(r"flyrobo\.in/.+", re.I),
    "CampusComponent": re.compile(r"campuscomponent\.com/.+", re.I),
    "Robu.in": re.compile(r"robu\.in/.+", re.I),
    "Evelta": re.compile(r"evelta\.com/.+", re.I),
}

_URL_DENY: Dict[str, re.Pattern[str]] = {
    "Rhydolabz": re.compile(
        r"(?i)(/image/|/catalog/|/information|/index\.php|route=|/blog)",
    ),
    "ElectronicsComp": re.compile(
        r"(?i)(/category|/brand|/blog|/page|/account|/cart|/manufacturer|"
        r"/index\.php|/information)",
    ),
    "Robokits": re.compile(r"(?i)(/sitemap|/category|/categories)"),
    "ElectronicsSpices": re.compile(r"(?i)/product-category/"),
    "DNATech": re.compile(r"(?i)(/sitemap|/category|/blog)"),
}


def _client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30.0,
        follow_redirects=True,
        verify=False,
    )


def _decode_body(url: str, content: bytes) -> str:
    if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
        except OSError:
            pass
    return content.decode("utf-8", errors="replace")


def _locs(xml: str) -> List[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml, re.I)


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _is_product_url(source_name: str, url: str) -> bool:
    if _DEFAULT_SKIP.search(url):
        return False
    deny = _URL_DENY.get(source_name)
    if deny and deny.search(url):
        return False
    allow = _URL_ALLOW.get(source_name)
    if allow:
        return bool(allow.search(url))
    # Generic fallback: look like a product path.
    return bool(re.search(r"(?i)(/product|/products/|/p/|/shop/|/item/)", url))


def discover_sitemaps(base_url: str, client: httpx.Client) -> List[str]:
    base = base_url.rstrip("/")
    found: List[str] = []
    try:
        r = client.get(base + "/robots.txt", timeout=12.0)
        if r.status_code == 200:
            for m in re.finditer(r"(?i)Sitemap:\s*(\S+)", r.text):
                found.append(m.group(1).strip())
    except Exception:  # noqa: BLE001
        pass
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemaps.xml"):
        u = base + path
        if u not in found:
            found.append(u)
    return found


def collect_product_urls(
    source: dict,
    client: httpx.Client,
    max_urls: int = 25000,
) -> List[str]:
    """Walk sitemap index trees and return product page URLs."""
    name = source["name"]
    base = source["base_url"].rstrip("/")
    seeds = list(source.get("sitemaps") or []) or discover_sitemaps(base, client)
    queue: List[str] = list(seeds)
    seen_maps: set[str] = set()
    products: List[str] = []
    seen_prod: set[str] = set()

    while queue and len(products) < max_urls:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            resp = client.get(sm)
            if resp.status_code != 200:
                continue
            xml = _decode_body(sm, resp.content)
        except Exception:  # noqa: BLE001
            continue
        if "<loc>" not in xml.lower():
            continue

        for loc in _locs(xml):
            low = loc.lower()
            if "sitemap" in low or low.endswith(".xml") or low.endswith(".xml.gz"):
                if loc not in seen_maps:
                    queue.append(loc)
                continue
            if _is_product_url(name, loc) and loc not in seen_prod:
                seen_prod.add(loc)
                products.append(loc)
                if len(products) >= max_urls:
                    break
    return products


def _parse_json_ld_products(html: str) -> List[dict]:
    products: List[dict] = []
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                # Strip control chars that break strict JSON on some storefronts.
                cleaned = re.sub(r"[\x00-\x1f]", " ", raw).replace("\\/", "/")
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Regex fallback for Product blocks with broken JSON.
                if re.search(r'"@type"\s*:\s*"Product"', raw, re.I):
                    name_m = re.search(r'"name"\s*:\s*"([^"]{2,200})"', raw)
                    price_m = re.search(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', raw)
                    sku_m = re.search(r'"sku"\s*:\s*"([^"]+)"', raw)
                    avail_m = re.search(r'"availability"\s*:\s*"([^"]+)"', raw)
                    if name_m and price_m:
                        products.append({
                            "@type": "Product",
                            "name": name_m.group(1),
                            "sku": sku_m.group(1) if sku_m else "",
                            "offers": {
                                "price": price_m.group(1),
                                "availability": avail_m.group(1) if avail_m else "",
                            },
                        })
                continue
        stack: List[Any] = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            types = [str(x).lower() for x in types if x]
            if "product" in types:
                products.append(node)
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in node:
                    stack.append(node[key])
    return products


def _price_from_offers(offers: Any) -> Optional[float]:
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if not isinstance(offers, dict):
        return None
    raw = offers.get("price")
    if raw is None and isinstance(offers.get("lowPrice"), (str, int, float)):
        raw = offers.get("lowPrice")
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _in_stock_from_offers(offers: Any) -> bool:
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if not isinstance(offers, dict):
        return True
    avail = str(offers.get("availability") or "")
    return "outofstock" not in avail.lower()


def _first_meta(html: str, *patterns: str) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return _strip_tags(m.group(1))
    return None


def _parse_money(raw: str) -> Optional[float]:
    num = re.sub(r"[^0-9.]", "", (raw or "").replace(",", ""))
    if not num:
        return None
    try:
        val = float(num)
    except ValueError:
        return None
    return val if val > 0 else None


def extract_product(html: str, url: str) -> Optional[Dict[str, Any]]:
    """Pull title/price/sku/stock from a product HTML page."""
    if not html or len(html) < 200:
        return None
    # Bot walls / soft blocks
    head = html[:800].lower()
    if "confirm you are not bot" in head or "just a moment" in head:
        return None
    if "the page you requested cannot be found" in head:
        return None

    brand_names = {
        "robokits india", "dna solutions", "sunrom electronics",
        "home", "shop", "dna solutions – online electronic components shop",
    }

    title = ""
    price: Optional[float] = None
    sku = ""
    in_stock = True

    for prod in _parse_json_ld_products(html):
        name = str(prod.get("name") or "").strip()
        offers = prod.get("offers")
        p = _price_from_offers(offers)
        if p is not None:
            price = p
            in_stock = _in_stock_from_offers(offers)
        if prod.get("sku"):
            sku = str(prod.get("sku"))
        elif prod.get("mpn"):
            sku = str(prod.get("mpn"))
        if name and name.lower() not in brand_names:
            # Prefer a longer, more specific product name if several Product blocks exist.
            if len(name) > len(title):
                title = name
        if title and price is not None:
            break

    if not title:
        title = (
            _first_meta(
                html,
                r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
            )
            or _first_meta(html, r"<h1[^>]*>(.*?)</h1>")
            or _first_meta(html, r"<title>(.*?)</title>")
            or ""
        )
        for sep in (" : ", " | ", " – ", " - "):
            if sep in title:
                left, right = title.split(sep, 1)
                title = left if len(left) >= len(right) else right
                break
        if title.lower().startswith("robokits india"):
            title = re.sub(r"(?i)^robokits india\s*[-–:]\s*", "", title).strip()

    # Prefer a visible H1 when JSON-LD only gave a store brand.
    if not title or title.lower() in brand_names:
        h1 = _first_meta(html, r"<h1[^>]*>(.*?)</h1>")
        if h1 and h1.lower() not in brand_names:
            title = h1

    if price is None:
        raw = _first_meta(
            html,
            r'Price:\s*<span[^>]*class=["\'][^"\']*label-product[^"\']*["\'][^>]*>\s*(?:Rs\.?|[\u20b9])?\s*([0-9,]+\.?[0-9]*)',
            r'property=["\']product:price:amount["\'][^>]*content=["\']([0-9.]+)',
            r'itemprop=["\']price["\'][^>]*content=["\']([0-9.]+)',
            r'content=["\']([0-9.]+)["\'][^>]*itemprop=["\']price["\']',
            r'id=["\']price[_-]?old["\'][^>]*>\s*(?:Rs\.?|[\u20b9])?\s*([0-9,]+\.?[0-9]*)',
            r'id=["\']price[_-]?new["\'][^>]*>\s*(?:Rs\.?|[\u20b9]|<[^>]+>)*\s*([0-9,]+\.?[0-9]*)',
            r'"price"\s*:\s*"(?:Rs\.?|[\u20b9])?\s*([0-9,]+\.?[0-9]*)"',
            r'class=["\'][^"\']*product-price[^"\']*["\'][^>]*>\s*(?:<[^>]+>\s*)*([\u20b9Rs\.\s,0-9]+)',
            r'data-product-price(?:-value)?=["\']([0-9.]+)',
            r'data-price=["\']([0-9.]+)',
        )
        if raw:
            price = _parse_money(raw)

    if not title or price is None or price <= 0:
        return None

    title = _strip_tags(title)
    if len(title) < 3 or title.lower() in brand_names:
        return None

    return {
        "title": title[:500],
        "sku": (sku or "")[:120],
        "price": round(float(price), 2),
        "in_stock": bool(in_stock),
        "product_url": url,
        "vendor": "",
    }


def crawl_html_source(
    source: dict,
    max_products: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch product pages for one HTML source; return extracted dicts."""
    import time

    cap = max_products if max_products is not None else min(
        settings.scrape_max_products * 40,  # allow large catalog builds
        15000,
    )
    # Honour explicit per-source override.
    if source.get("max_products"):
        try:
            cap = int(source["max_products"])
        except (TypeError, ValueError):
            pass

    rows: List[Dict[str, Any]] = []
    with _client() as client:
        # Quick home check — skip hard Cloudflare 403s early.
        try:
            home = client.get(source["base_url"], timeout=15.0)
            body = home.text[:1000].lower()
            if home.status_code in (403, 503) or "just a moment" in body:
                print(f"[html] {source['name']}: blocked (status={home.status_code})")
                return []
        except Exception as exc:  # noqa: BLE001
            print(f"[html] {source['name']}: home failed: {exc}")
            return []

        urls = collect_product_urls(source, client, max_urls=cap)
        print(f"[html] {source['name']}: {len(urls)} product URLs (cap={cap})")
        empty_streak = 0
        for i, url in enumerate(urls):
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    empty_streak += 1
                    continue
                got = extract_product(resp.text, str(resp.url))
                if got is not None:
                    rows.append(got)
                    empty_streak = 0
                else:
                    empty_streak += 1
            except Exception:  # noqa: BLE001
                empty_streak += 1
                continue
            if (i + 1) % 50 == 0:
                print(f"[html] {source['name']}: fetched {i + 1}/{len(urls)}, kept {len(rows)}")
            # Bail early on bot-walls / unparseable catalogs (e.g. Semikart).
            if i >= 40 and len(rows) == 0 and empty_streak >= 40:
                print(f"[html] {source['name']}: aborting — 0 usable products in first {i + 1} pages")
                break
            time.sleep(settings.scrape_min_interval_seconds)
    return rows
