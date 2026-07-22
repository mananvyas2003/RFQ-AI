"""Central configuration loaded from environment variables / a `.env` file.

Nothing here is required to run the MVP on mock data. Populate the values (or a
`.env` file) to activate real data sources and persistence:

- NEXAR_CLIENT_ID / NEXAR_CLIENT_SECRET -> real global offers (Tier 1).
- DATABASE_URL -> where cached offers + saved runs live (defaults to a local
  SQLite file, so no setup is needed).
- STORES_CONFIG -> path to a JSON file describing Shopify / WooCommerce stores.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Tier 1: Nexar / Octopart (global distributors) ---------------------
    nexar_client_id: str = ""
    nexar_client_secret: str = ""
    nexar_token_url: str = "https://identity.nexar.com/connect/token"
    nexar_api_url: str = "https://api.nexar.com/graphql"
    # Max offers to pull per part from Nexar (each returned part counts toward
    # your Nexar part limit, so keep this modest).
    nexar_limit: int = 5
    # Ask Nexar to prioritise offers that can ship to this country.
    nexar_ship_to: str = "IN"

    # --- Database / caching -------------------------------------------------
    database_url: str = "sqlite:///./rfq_ai.db"
    # How long a cached offer set stays fresh before we re-query the source.
    cache_ttl_hours: int = 24

    # --- Tier 2: platform stores -------------------------------------------
    # Path to a JSON file listing Shopify / WooCommerce stores to query.
    stores_config: str = ""

    # --- Tier 3: scraping (last resort, off by default) --------------------
    # Master switch. Even when true, only sources listed in the "scrape" section
    # of STORES_CONFIG are ever fetched (consent-first, per-source allow-list).
    scrape_enabled: bool = False
    # Politeness: minimum seconds between requests to the same host.
    scrape_min_interval_seconds: float = 1.0
    # Cap how many products we scan per store per lookup.
    scrape_max_products: int = 250
    # Relevance gate for scraped hits. Maker stores return keyword-ranked
    # products, so a search for a resistor can surface a "load cell" that merely
    # shares the text "10K". When true, a scraped product is only accepted if it
    # actually corresponds to the part (MPN/core/description overlap), otherwise
    # the line is reported as "no match" instead of a wrong product.
    scrape_strict_matching: bool = True
    # Fraction of the meaningful description tokens (value + component type) that
    # must appear in the product title for a description-based match to count.
    scrape_match_min_coverage: float = 0.6

    @property
    def nexar_enabled(self) -> bool:
        return bool(self.nexar_client_id and self.nexar_client_secret)


settings = Settings()
