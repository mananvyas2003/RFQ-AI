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

    @property
    def nexar_enabled(self) -> bool:
        return bool(self.nexar_client_id and self.nexar_client_secret)


settings = Settings()
