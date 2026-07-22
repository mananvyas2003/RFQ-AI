"""Database setup (SQLAlchemy).

Defaults to a local SQLite file (`rfq_ai.db`) so the app is persistent with zero
setup. Point `DATABASE_URL` at Postgres/MySQL/etc. to use a hosted database
instead - nothing else in the code changes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OfferCache(Base):
    """Cached offer payload for one (source, mpn) pair.

    Stores the JSON-serialized list of `Offer`s a provider returned so we don't
    re-hit paid/rate-limited APIs for the same part within the TTL window.
    """

    __tablename__ = "offer_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    mpn: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON list[Offer]
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SavedRun(Base):
    """A persisted sourcing run, so results survive a page refresh / restart."""

    __tablename__ = "saved_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    destination_country: Mapped[str] = mapped_column(String(8), default="IN")
    objective: Mapped[str] = mapped_column(String(16), default="cost")
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ScrapedProduct(Base):
    """One product harvested from a distributor's public catalog by the crawler.

    This is the searchable local catalog: BOM lookups query this table instead of
    hitting the live sites, and the crawler refreshes it from time to time.
    """

    __tablename__ = "scraped_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), index=True)  # distributor name
    title: Mapped[str] = mapped_column(String(512), default="")
    sku: Mapped[str] = mapped_column(String(128), default="", index=True)
    vendor: Mapped[str] = mapped_column(String(128), default="")
    price: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    in_stock: Mapped[bool] = mapped_column(default=True)
    region: Mapped[str] = mapped_column(String(8), default="IN")
    product_url: Mapped[str] = mapped_column(String(1024), default="")
    # Lower-cased, alnum+space normalized haystack used for fast token matching.
    search_text: Mapped[str] = mapped_column(Text, default="", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)
