"""网页数据接口（/api/ui）"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app import services

router = APIRouter(prefix="/api/ui", tags=["web-ui"])


@router.get("/summary")
def ui_summary():
    return {"code": 0, "message": "ok", "data": services.summary()}


@router.get("/import-logs")
def ui_import_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    return {
        "code": 0,
        "message": "ok",
        "data": services.list_import_batches(page=page, page_size=page_size),
    }


@router.get("/push-logs")
def ui_push_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    return {
        "code": 0,
        "message": "ok",
        "data": services.list_push_batches(page=page, page_size=page_size),
    }


@router.get("/records")
def ui_records(
    asin: str = Query(default=""),
    shipment_id: str = Query(default=""),
    keyword: str = Query(default=""),
    has_eta: str = Query(default="", description="空=全部 / true=有到港时间 / false=无到港时间"),
    eta_from: str = Query(default=""),
    eta_to: str = Query(default=""),
    source_file: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    has_eta_value = None
    if str(has_eta).strip().lower() == "true":
        has_eta_value = True
    elif str(has_eta).strip().lower() == "false":
        has_eta_value = False
    data = services.query_records(
        asin=asin,
        shipment_id=shipment_id,
        keyword=keyword,
        has_eta=has_eta_value,
        eta_from=eta_from or None,
        eta_to=eta_to or None,
        source_file=source_file,
        page=page,
        page_size=page_size,
    )
    return {"code": 0, "message": "ok", "data": data}
