"""Local scrape-catalog management endpoints.

- POST /catalog/refresh -> (re)crawl allow-listed stores into the DB (background).
- GET  /catalog/stats   -> product counts + last-updated per source.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, BackgroundTasks

from app.services.catalog.crawler import catalog_stats, crawl_all

router = APIRouter(prefix="/catalog", tags=["catalog"])

_crawl_lock = threading.Lock()
_crawling = {"running": False}


def _run_crawl() -> None:
    if not _crawl_lock.acquire(blocking=False):
        return
    try:
        _crawling["running"] = True
        crawl_all()
    finally:
        _crawling["running"] = False
        _crawl_lock.release()


@router.post("/refresh")
def refresh(background_tasks: BackgroundTasks) -> dict:
    if _crawling["running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_crawl)
    return {"status": "started", "note": "Crawl running in background. Check /catalog/stats."}


@router.get("/stats")
def stats() -> dict:
    return {"crawling": _crawling["running"], **catalog_stats()}
