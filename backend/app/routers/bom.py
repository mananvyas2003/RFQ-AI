"""BOM parsing and sourcing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models import ParseResponse, SourceRequest, SourcingResult
from app.services.optimizer import source_bom
from app.services.parser import parse_bom

router = APIRouter(prefix="/bom", tags=["bom"])

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/parse", response_model=ParseResponse)
async def parse(file: UploadFile = File(...)) -> ParseResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB).")
    try:
        return parse_bom(file.filename or "bom.csv", content)
    except Exception as exc:  # noqa: BLE001 - surface a clean parse error to the UI
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}") from exc


@router.post("/source", response_model=SourcingResult)
async def source(request: SourceRequest) -> SourcingResult:
    if not request.lines:
        raise HTTPException(status_code=400, detail="No BOM lines provided.")
    return source_bom(request)
