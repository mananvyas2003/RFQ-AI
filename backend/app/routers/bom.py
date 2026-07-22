"""BOM parsing and sourcing endpoints."""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.models import ParseResponse, SourceRequest, SourcingResult
from app.services.export import build_sourcing_workbook
from app.services.optimizer import source_bom
from app.services.parser import parse_bom

router = APIRouter(prefix="/bom", tags=["bom"])
logger = logging.getLogger("rfq.bom")

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/parse", response_model=ParseResponse)
async def parse(file: UploadFile = File(...)) -> ParseResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB).")
    try:
        result = parse_bom(file.filename or "bom.csv", content)
    except Exception as exc:  # noqa: BLE001 - surface a clean parse error to the UI
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}") from exc
    # Counts only — BOM contents are confidential customer IP.
    logger.info("parse rows=%s", result.row_count)
    return result


@router.post("/source", response_model=SourcingResult)
async def source(request: SourceRequest) -> SourcingResult:
    if not request.lines:
        raise HTTPException(status_code=400, detail="No BOM lines provided.")
    result = source_bom(request)
    # Counts only — never log MPNs, descriptions, or supplier picks.
    logger.info(
        "source coverage=%s/%s (%.0f%%)",
        result.summary.lines_matched,
        result.summary.lines_total,
        (result.summary.line_coverage or 0.0) * 100,
    )
    return result


@router.post("/export")
async def export(request: SourceRequest) -> StreamingResponse:
    """Source the BOM and return an Excel order sheet (Supplier + cart links)."""
    if not request.lines:
        raise HTTPException(status_code=400, detail="No BOM lines provided.")
    result = source_bom(request)
    workbook = build_sourcing_workbook(result)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="rfq_order_sheet.xlsx"'},
    )
