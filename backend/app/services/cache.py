"""Offer cache: read/write provider results through the database with a TTL.

Live providers (Nexar, Shopify, WooCommerce) wrap their network calls with this
so repeated lookups for the same part are served from the DB instead of burning
API quota. Falls back to "no cache" gracefully if the DB is unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import delete, select

from app.config import settings
from app.db import OfferCache, SessionLocal
from app.models import Offer

logger = logging.getLogger(__name__)


def _key(mpn: str) -> str:
    return mpn.strip().upper()


def get_cached_offers(source: str, mpn: str) -> Optional[List[Offer]]:
    """Return cached offers if a fresh entry exists, else None (a cache miss).

    An empty list is a valid cached value (the source genuinely had nothing),
    which lets us avoid re-querying for parts a source doesn't carry.
    """
    key = _key(mpn)
    if not key:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.cache_ttl_hours)
    try:
        with SessionLocal() as db:
            row = db.scalar(
                select(OfferCache)
                .where(OfferCache.source == source, OfferCache.mpn == key)
                .order_by(OfferCache.fetched_at.desc())
            )
            if row is None:
                return None
            fetched = row.fetched_at
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            if fetched < cutoff:
                return None
            import json

            return [Offer(**o) for o in json.loads(row.payload)]
    except Exception as exc:  # noqa: BLE001 - cache must never break the request path
        logger.warning("offer cache read failed: %s", exc)
        return None


def set_cached_offers(source: str, mpn: str, offers: List[Offer]) -> None:
    key = _key(mpn)
    if not key:
        return
    import json

    payload = json.dumps([o.model_dump() for o in offers])
    try:
        with SessionLocal() as db:
            db.execute(
                delete(OfferCache).where(OfferCache.source == source, OfferCache.mpn == key)
            )
            db.add(OfferCache(source=source, mpn=key, payload=payload))
            db.commit()
    except Exception as exc:  # noqa: BLE001 - caching is best-effort
        logger.warning("offer cache write failed: %s", exc)
