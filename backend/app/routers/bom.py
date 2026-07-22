"""BOM parsing and sourcing endpoints."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path

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
_DEBUG_PATH = Path(__file__).resolve().parents[2] / "last_source_debug.json"


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
    logger.warning(
        "parse file=%s rows=%s mapping=%s sample=%s",
        file.filename,
        result.row_count,
        result.mapping.model_dump(),
        [ln.model_dump() for ln in result.lines[:5]],
    )
    return result


@router.post("/source", response_model=SourcingResult)
async def source(request: SourceRequest) -> SourcingResult:
    if not request.lines:
        raise HTTPException(status_code=400, detail="No BOM lines provided.")
    result = source_bom(request)
    debug = {
        "input_lines": [ln.model_dump() for ln in request.lines],
        "summary": result.summary.model_dump(),
        "results": [
            {
                "mpn": ln.input.mpn,
                "description": ln.input.description,
                "status": ln.status.value,
                "matched_mpn": ln.matched_mpn,
                "distributor": ln.chosen.offer.distributor if ln.chosen else None,
                "product": (ln.chosen.offer.description if ln.chosen else None),
            }
            for ln in result.lines
        ],
    }
    try:
        _DEBUG_PATH.write_text(json.dumps(debug, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    logger.warning(
        "source coverage=%s/%s lines=%s",
        result.summary.lines_matched,
        result.summary.lines_total,
        [
            {
                "mpn": ln.input.mpn,
                "desc": ln.input.description,
                "dist": ln.chosen.offer.distributor if ln.chosen else None,
            }
            for ln in result.lines
        ],
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
