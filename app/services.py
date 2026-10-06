"""业务核心：物流记录 upsert、到货时间查询、全量导出"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, List, Optional

from app import db
from app.config import settings
from app.dates import arrival_date, to_iso

logger = logging.getLogger("logistics.services")


def _now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_date(value, anchor: Optional[dt.date]) -> Optional[str]:
    return to_iso(value, anchor)


def upsert_records(
    records: List[dict],
    *,
    source_file: str,
    anchor: Optional[dt.date] = None,
    capture_at: Optional[str] = None,
) -> Dict[str, int]:
    """更新当前快照，并把每条原始记录追加进历史表（历史只追加、不覆盖）"""
    inserted = 0
    updated = 0
    skipped = 0
    with db.transaction() as conn:
        for raw in records:
            shipment_id = str(raw.get("shipment_id") or "").strip()
            asin = str(raw.get("asin") or "").strip().upper()
            if not shipment_id or not asin:
                skipped += 1
                continue
            product_name = str(raw.get("product_name") or "").strip()
            quantity = str(raw.get("quantity") or "").strip()
            channel = str(raw.get("channel") or "").strip()
            tracking_numbers = str(raw.get("tracking_numbers") or "").strip()
            sailing = _normalize_date(raw.get("sailing_date"), anchor)
            eta = _normalize_date(raw.get("eta_date"), anchor)
            inspection = str(raw.get("inspection") or "").strip()
            now = _now_iso()
            cap_at = capture_at or now
            exists = conn.execute(
                "SELECT 1 FROM shipment_items WHERE shipment_id=? AND asin=?",
                (shipment_id, asin),
            ).fetchone()
            if exists:
                updated += 1
                conn.execute(
                    """
                    UPDATE shipment_items
                       SET product_name=?, quantity=?, channel=?,
                           tracking_numbers=?, sailing_date=?, eta_date=?,
                           inspection=?, source_file=?, last_updated_at=?
                     WHERE shipment_id=? AND asin=?
                    """,
                    (
                        product_name,
                        quantity,
                        channel,
                        tracking_numbers,
                        sailing,
                        eta,
                        inspection,
                        source_file,
                        now,
                        shipment_id,
                        asin,
                    ),
                )
            else:
                inserted += 1
                conn.execute(
                    """
                    INSERT INTO shipment_items (
                        shipment_id, asin, product_name, quantity, channel,
                        tracking_numbers, sailing_date, eta_date, inspection,
                        source_file, first_seen_at, last_updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        shipment_id,
                        asin,
                        product_name,
                        quantity,
                        channel,
                        tracking_numbers,
                        sailing,
                        eta,
                        inspection,
                        source_file,
                        now,
                        now,
                    ),
                )
            # 原始行历史：一律追加，不覆盖
            conn.execute(
                """
                INSERT INTO logistics_history (
                    shipment_id, asin, product_name, quantity, channel,
                    tracking_numbers, sailing_date, eta_date, inspection,
                    source_file, capture_at, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    shipment_id,
                    asin,
                    product_name,
                    quantity,
                    channel,
                    tracking_numbers,
                    sailing,
                    eta,
                    inspection,
                    source_file,
                    cap_at,
                    now,
                ),
            )
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _normalized_row(row: dict) -> dict:
    eta = row.get("eta_date")
    out = {
        "asin": row.get("asin"),
        "shipment_id": row.get("shipment_id"),
        "product_name": row.get("product_name"),
        "quantity": row.get("quantity"),
        "channel": row.get("channel"),
        "tracking_numbers": row.get("tracking_numbers"),
        "sailing_date": row.get("sailing_date"),
        "eta_date": eta,
        "arrival_date": arrival_date(eta),
        "inspection": row.get("inspection"),
        "source_file": row.get("source_file"),
        "last_updated_at": (
            row.get("last_updated_at")
            or row.get("capture_at")
            or row.get("created_at")
        ),
    }
    return out


def query_arrival(
    asins: Optional[List[str]] = None,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    upcoming_only: bool = False,
) -> List[dict]:
    """按 ASIN 查询到货时间（仅返回有预计到港时间的记录）"""
    conds = ["eta_date IS NOT NULL", "eta_date <> ''"]
    params: list = []
    if asins:
        placeholders = ",".join("?" for _ in asins)
        conds.append(f"asin IN ({placeholders})")
        params.extend(asins)
    sql = """
        SELECT * FROM shipment_items
         WHERE {where}
         ORDER BY asin ASC, eta_date ASC, shipment_id ASC
    """.format(where=" AND ".join(conds))
    rows = db.fetchall(sql, *params)
    out = []
    today = dt.datetime.now().astimezone().date().isoformat()
    for row in rows:
        item = _normalized_row(row)
        arrival = item.get("arrival_date")
        if upcoming_only and arrival and arrival < today:
            continue
        if arrival and start_date and arrival < start_date:
            continue
        if arrival and end_date and arrival > end_date:
            continue
        out.append(item)
    return out


def export_arrivals(
    *,
    earliest_only: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    upcoming_only: bool = False,
) -> Dict:
    """所有 [ASIN, 到货时间] 列表，供其他系统入库。

    earliest_only=true 时每个 ASIN 只保留最早一条到货时间。
    """
    rows = query_arrival(
        None, start_date=start_date, end_date=end_date, upcoming_only=upcoming_only
    )
    return build_export_from_rows(rows, earliest_only=earliest_only)


def build_export_from_rows(rows: List[dict], *, earliest_only: bool = False) -> Dict:
    pairs: List[dict] = []
    seen_pairs = set()
    seen_asin = set()
    for item in rows:
        arrival = item.get("arrival_date")
        asin = item.get("asin")
        if not arrival:
            continue
        pair_key = (asin, arrival)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        if earliest_only and asin in seen_asin:
            continue
        seen_asin.add(asin)
        pairs.append({"asin": asin, "time": arrival})
    pairs.sort(key=lambda x: (x["asin"], x["time"]))
    return {
        "items": pairs,
        "total": len(pairs),
        "earliest_only": earliest_only,
        "generated_at": _now_iso(),
    }


def summary() -> dict:
    total_file_rows = db.fetchone(
        "SELECT count(*) AS n FROM logistics_history"
    ) or {}
    total = db.fetchone("SELECT count(*) AS n FROM shipment_items") or {}
    total_with_eta = db.fetchone(
        "SELECT count(*) AS n FROM shipment_items "
        "WHERE eta_date IS NOT NULL AND eta_date <> ''"
    ) or {}
    asin_count = db.fetchone(
        "SELECT count(DISTINCT asin) AS n FROM shipment_items"
    ) or {}
    last_import = db.fetchone(
        "SELECT * FROM import_batches ORDER BY id DESC LIMIT 1"
    )
    last_push = db.fetchone("SELECT * FROM push_batches ORDER BY id DESC LIMIT 1")
    return {
        "total_file_rows": int(total_file_rows.get("n") or 0),
        "total_records": int(total.get("n") or 0),
        "records_with_eta": int(total_with_eta.get("n") or 0),
        "distinct_asins": int(asin_count.get("n") or 0),
        "arrival_offset_days": settings.arrival_offset_days,
        "last_import": last_import,
        "last_push": last_push,
    }


def list_import_batches(page: int = 1, page_size: int = 50) -> dict:
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 200)
    total = db.fetchone("SELECT count(*) AS n FROM import_batches") or {}
    rows = db.fetchall(
        """
        SELECT * FROM import_batches
         ORDER BY id DESC
         LIMIT ? OFFSET ?
        """,
        page_size,
        (page - 1) * page_size,
    )
    return {
        "items": rows,
        "total": int(total.get("n") or 0),
        "page": page,
        "page_size": page_size,
    }


def list_push_batches(page: int = 1, page_size: int = 50) -> dict:
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 200)
    total = db.fetchone("SELECT count(*) AS n FROM push_batches") or {}
    rows = db.fetchall(
        """
        SELECT * FROM push_batches
         ORDER BY id DESC
         LIMIT ? OFFSET ?
        """,
        page_size,
        (page - 1) * page_size,
    )
    return {
        "items": rows,
        "total": int(total.get("n") or 0),
        "page": page,
        "page_size": page_size,
    }


def query_records(
    *,
    asin: str = "",
    shipment_id: str = "",
    keyword: str = "",
    has_eta: Optional[bool] = None,
    eta_from: Optional[str] = None,
    eta_to: Optional[str] = None,
    source_file: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """物流表原始数据查询（带分页）"""
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 500)
    conds: List[str] = []
    params: list = []

    asin_text = str(asin or "").strip().upper()
    if asin_text:
        conds.append("asin = ?")
        params.append(asin_text)
    shipment_text = str(shipment_id or "").strip()
    if shipment_text:
        conds.append("shipment_id LIKE ?")
        params.append(f"%{shipment_text}%")
    keyword_text = str(keyword or "").strip()
    if keyword_text:
        like = f"%{keyword_text}%"
        conds.append(
            "(product_name LIKE ? OR channel LIKE ? OR tracking_numbers LIKE ? "
            "OR shipment_id LIKE ?)"
        )
        params.extend([like, like, like, like])
    if has_eta is True:
        conds.append("eta_date IS NOT NULL AND eta_date <> ''")
    elif has_eta is False:
        conds.append("(eta_date IS NULL OR eta_date = '')")
    if eta_from:
        conds.append("eta_date >= ?")
        params.append(str(eta_from))
    if eta_to:
        conds.append("eta_date <= ?")
        params.append(str(eta_to))
    source_text = str(source_file or "").strip()
    if source_text:
        conds.append("source_file LIKE ?")
        params.append(f"%{source_text}%")

    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    total_row = db.fetchone(
        f"SELECT count(*) AS n FROM logistics_history {where}", params
    ) or {}
    rows = db.fetchall(
        f"""
        SELECT * FROM logistics_history
          {where}
         ORDER BY capture_at DESC, id DESC
         LIMIT ? OFFSET ?
        """,
        [*params, page_size, (page - 1) * page_size],
    )
    items = [_normalized_row(r) for r in rows]
    return {
        "items": items,
        "total": int(total_row.get("n") or 0),
        "page": page,
        "page_size": page_size,
    }
