"""Per-site extraction recipes for custom (non-Shopify/Woo) distributor sites.

Some Indian distributors run bespoke storefronts with no Shopify/WooCommerce
JSON API and no JSON-LD, so they can only be harvested by crawling their
sitemap and parsing each product page's HTML. Each site's markup differs, so we
keep a small, declarative "recipe" per site (which sitemap to read, which URLs
are products, and regexes for title/price/stock). Adding a new custom site is
just one more entry here plus a `stores.json` line with platform "html_sitemap".

Consent-first still applies: a site is only crawled if it's in the allow-listed
"scrape" section of stores.json.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(fragment: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", fragment or "")).strip()


@dataclass
class HtmlRecipe:
    name: str
    sitemap_urls: List[str]
    product_url_substr: str          # keep a sitemap URL only if it contains this
    title_pattern: str               # regex; group 1 -> title (may contain tags)
    price_pattern: str               # regex; group 1 -> price (digits/commas/dot)
    sku_pattern: str = ""            # optional; group 1 -> sku/code
    out_of_stock_marker: str = ""    # if present (case-insensitive) -> out of stock
    currency: str = "INR"
    region: str = "IN"
    lead_time_days: int = 5
    _title_re: re.Pattern = field(init=False, repr=False)
    _price_re: re.Pattern = field(init=False, repr=False)
    _sku_re: Optional[re.Pattern] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._title_re = re.compile(self.title_pattern, re.S | re.I)
        self._price_re = re.compile(self.price_pattern, re.S | re.I)
        if self.sku_pattern:
            self._sku_re = re.compile(self.sku_pattern, re.S | re.I)

    def extract(self, html: str) -> Optional[dict]:
        """Return {title, price, sku, in_stock} or None if not a usable product."""
        tm = self._title_re.search(html)
        pm = self._price_re.search(html)
        if not tm or not pm:
            return None
        title = _text(tm.group(1))
        raw = re.sub(r"[^0-9.]", "", pm.group(1).replace(",", ""))
        try:
            price = float(raw)
        except ValueError:
            return None
        if not title or price <= 0:
            return None
        sku = ""
        if self._sku_re is not None:
            sm = self._sku_re.search(html)
            if sm:
                sku = sm.group(1).strip()
        in_stock = True
        if self.out_of_stock_marker and self.out_of_stock_marker.lower() in html.lower():
            in_stock = False
        return {"title": title, "price": price, "sku": sku, "in_stock": in_stock}


# --- Registry of supported custom sites ------------------------------------
RECIPES: dict[str, HtmlRecipe] = {
    "Sunrom": HtmlRecipe(
        name="Sunrom",
        sitemap_urls=["https://www.sunrom.com/sitemap.xml"],
        product_url_substr="/p/",
        title_pattern=r"<h1[^>]*>(.*?)</h1>",
        price_pattern=r'class="pprice">\s*Rs\.?\s*([0-9,]+(?:\.[0-9]+)?)',
        sku_pattern=r"\[(\d{2,})\]\s*:\s*Sunrom",
        out_of_stock_marker="out of stock",
        lead_time_days=5,
    ),
}


def recipe_for(source: dict) -> Optional[HtmlRecipe]:
    return RECIPES.get(source.get("name", ""))
