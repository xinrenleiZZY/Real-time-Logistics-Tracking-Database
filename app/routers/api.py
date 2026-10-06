"""开放 API（/api/v1）"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app import db, services
from app.config import settings
from app.dates import to_iso
from app.schemas import AsinQuery, PushBatch

router = APIRouter(prefix="/api/v1", tags=["open-api"])


def _envelope(
    code: int, message: str, data=None, meta: Optional[dict] = None
) -> dict:
    return {"code": code, "message": message, "data": data, "meta": meta or {}}


def _guard(header_value: Optional[str], token: str, name: str) -> None:
    if not token:
        return
    import hmac

    if not header_value or not hmac.compare_digest(header_value.strip(), token):
        raise HTTPException(status_code=401, detail=f"{name} 无效或缺失")


def api_token_guard(
    x_api_token: Optional[str] = Header(default=None, alias="X-API-Token"),
) -> None:
    _guard(x_api_token, settings.api_token, "API Token")


def push_token_guard(
    x_push_token: Optional[str] = Header(default=None, alias="X-Push-Token"),
) -> None:
    _guard(x_push_token, settings.push_token, "推送令牌")


def _split_asins(raw: str) -> List[str]:
    items = []
    for part in str(raw or "").replace(";", ",").replace("，", ",").split(","):
        text = part.strip().upper()
        if text and text not in items:
            items.append(text)
    return items


def settings_max_asins() -> int:
    return 200


def _validate_dates(
    start_date: Optional[str], end_date: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    def norm(value: Optional[str]) -> Optional[str]:
        if value is None or str(value).strip() == "":
            return None
        iso = to_iso(str(value).strip())
        if not iso:
            raise HTTPException(status_code=400, detail=f"日期格式不正确: {value}")
        return iso

    return norm(start_date), norm(end_date)


@router.get("/arrival/query", summary="按 ASIN 查询到货时间（支持多个，逗号分隔）")
def get_arrival_query(
    asins: str = Query(..., description="ASIN 列表，逗号/分号分隔"),
    start_date: Optional[str] = Query(default=None, description="到货时间起 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="到货时间止 YYYY-MM-DD"),
    upcoming_only: bool = Query(default=False, description="true=只看今天之后的到货"),
    _guard_ok: None = Depends(api_token_guard),
):
    asin_list = _split_asins(asins)
    if not asin_list:
        raise HTTPException(status_code=400, detail="请至少提供一个 ASIN")
    if len(asin_list) > settings_max_asins():
        raise HTTPException(status_code=400, detail=f"单次最多查询 {settings_max_asins()} 个 ASIN")
    start, end = _validate_dates(start_date, end_date)
    items = services.query_arrival(
        asin_list, start_date=start, end_date=end, upcoming_only=upcoming_only
    )
    return _envelope(
        0,
        "ok",
        {
            "items": items,
            "total": len(items),
            "arrival_offset_days": settings.arrival_offset_days,
        },
    )


@router.post("/arrival/query", summary="按 ASIN 列表查询到货时间（POST 方式）")
def post_arrival_query(
    body: AsinQuery,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    upcoming_only: bool = Query(default=False),
    _guard_ok: None = Depends(api_token_guard),
):
    start, end = _validate_dates(start_date, end_date)
    items = services.query_arrival(
        body.asins, start_date=start, end_date=end, upcoming_only=upcoming_only
    )
    return _envelope(
        0,
        "ok",
        {
            "items": items,
            "total": len(items),
            "arrival_offset_days": settings.arrival_offset_days,
        },
    )


@router.get("/arrival/export", summary="导出全部 [ASIN, 到货时间]，供其他系统入库")
def export_arrivals(
    earliest_only: bool = Query(default=False, description="true=每个 ASIN 只返回最早一条"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    upcoming_only: bool = Query(default=False, description="true=只看今天之后的到货"),
    _guard_ok: None = Depends(api_token_guard),
):
    start, end = _validate_dates(start_date, end_date)
    data = services.export_arrivals(
        earliest_only=earliest_only,
        start_date=start,
        end_date=end,
        upcoming_only=upcoming_only,
    )
    return _envelope(0, "ok", data)


@router.get("/arrival/all", summary="同 /arrival/export（保留别名）")
def arrival_all(
    earliest_only: bool = Query(default=False),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    upcoming_only: bool = Query(default=False),
    _guard_ok: None = Depends(api_token_guard),
):
    return export_arrivals(earliest_only, start_date, end_date, upcoming_only)


@router.post("/records/push", summary="接收其他系统推送的物流表 JSON 数据")
def push_records(
    body: PushBatch,
    _push_ok: None = Depends(push_token_guard),
    _api_ok: None = Depends(api_token_guard),
):
    anchor = None
    if body.data_date:
        anchor = to_iso(body.data_date)
        try:
            anchor = dt.date.fromisoformat(anchor)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="data_date 格式应为 YYYY-MM-DD"
            )
    source = body.source.strip()
    push_id = (body.push_id or "").strip() or str(uuid.uuid4())

    # push_id + source 幂等：重复推送不再入库
    existing = db.fetchone(
        "SELECT 1 FROM push_batches WHERE source=? AND push_id=?",
        (source, push_id),
    )
    if existing:
        return _envelope(
            0,
            "重复推送已忽略（push_id 已处理过）",
            {
                "push_id": push_id,
                "duplicated": True,
                "accepted": 0,
                "inserted": 0,
                "updated": 0,
                "rejected": [],
            },
        )

    normalized: List[dict] = []
    rejected: List[dict] = []
    for idx, record in enumerate(body.records):
        try:
            row = record.normalized()
        except Exception as exc:
            rejected.append({"index": idx, "reason": f"字段无法解析: {exc}"})
            continue
        if not row.get("shipment_id") or not row.get("asin"):
            rejected.append(
                {
                    "index": idx,
                    "reason": "缺少货件单号或 ASIN",
                }
            )
            continue
        normalized.append(row)

    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    counts = services.upsert_records(
        normalized,
        source_file=f"push:{source}:{push_id}",
        anchor=anchor,
        capture_at=now,
    )
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO push_batches (
                push_id, source, received_at, total, inserted, updated, rejected
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                push_id,
                source,
                now,
                len(body.records),
                counts["inserted"],
                counts["updated"],
                len(rejected),
            ),
        )
    return _envelope(
        0,
        "修改更新成功",
        {
            "push_id": push_id,
            "duplicated": False,
            "source": source,
            "accepted": len(body.records) - len(rejected),
            "inserted": counts["inserted"],
            "updated": counts["updated"],
            "rejected": rejected,
        },
    )


@router.get("/summary", summary="系统数据概览")
def get_summary(_guard_ok: None = Depends(api_token_guard)):
    return _envelope(0, "ok", services.summary())
