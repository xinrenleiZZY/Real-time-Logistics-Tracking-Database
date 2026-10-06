"""一次性导入 E:\\ZY2026\\物流单跟踪\\output 下所有物流 Excel 到 SQLite

用法：
    python scripts/import_xlsx.py --dir "E:\\ZY2026\\物流单跟踪\\output"
    python scripts/import_xlsx.py --dir "E:\\ZY2026\\物流单跟踪\\output" --reset

规则：
- 跳过 Excel 临时锁文件（~$ 开头）
- 表头需包含 ASIN、货件单号（兼容品名/发货量等中文字段）
- 以 (货件单号, ASIN) 为唯一键 upsert，处理顺序按文件导出时间戳从旧到新
- “预计到港时间”为空或解析失败时 eta_date 为空，不产出到货时间
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook  # noqa: E402

from app import db, services  # noqa: E402

FIELD_ALIASES = {
    "品名": "product_name",
    "ASIN": "asin",
    "asin": "asin",
    "货件单号": "shipment_id",
    "shipment_id": "shipment_id",
    "发货量": "quantity",
    "quantity": "quantity",
    "物流渠道": "channel",
    "channel": "channel",
    "跟踪编号": "tracking_numbers",
    "tracking_numbers": "tracking_numbers",
    "开船时间": "sailing_date",
    "sailing_date": "sailing_date",
    "预计到港时间": "eta_date",
    "eta_date": "eta_date",
    "是否查验": "inspection",
    "inspection": "inspection",
}


def file_timestamp(path: Path) -> dt.datetime:
    """从文件名尾部 _YYYYMMDD_HHMMSS 解析导出时间，取不到则用文件修改时间"""
    m = re.search(r"_(\d{8})_(\d{6})\.xlsx$", path.name)
    if m:
        try:
            return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return dt.datetime.fromtimestamp(path.stat().st_mtime)


def _clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return text


def read_sheet(path: Path, ws) -> list[dict]:
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        return []
    mapping = {}
    for idx, col in enumerate(header):
        if col is None:
            continue
        name = str(col).strip()
        if name in FIELD_ALIASES:
            mapping[idx] = FIELD_ALIASES[name]
    if "asin" not in mapping.values() or "shipment_id" not in mapping.values():
        return []
    # 记录反查中文字段名用于警告
    col_index = {v: k for k, v in mapping.items()}
    out = []
    for row in rows_iter:
        rec = {
            "product_name": _clean(row[col_index["product_name"]])
            if "product_name" in col_index
            else "",
            "asin": _clean(row[col_index["asin"]]).upper(),
            "shipment_id": _clean(row[col_index["shipment_id"]]),
            "quantity": _clean(row[col_index["quantity"]])
            if "quantity" in col_index
            else "",
            "channel": _clean(row[col_index["channel"]])
            if "channel" in col_index
            else "",
            "tracking_numbers": _clean(row[col_index["tracking_numbers"]])
            if "tracking_numbers" in col_index
            else "",
            "sailing_date": _clean(row[col_index["sailing_date"]])
            if "sailing_date" in col_index
            else None,
            "eta_date": _clean(row[col_index["eta_date"]])
            if "eta_date" in col_index
            else None,
            "inspection": _clean(row[col_index["inspection"]])
            if "inspection" in col_index
            else "",
        }
        if rec["asin"] and rec["shipment_id"]:
            out.append(rec)
    return out


def import_directory(directory: Path, reset: bool = False) -> dict:
    db.init_schema()
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if reset:
        db.execute("DELETE FROM shipment_items")
        db.execute("DELETE FROM logistics_history")
        db.execute("DELETE FROM import_batches")
        db.execute("DELETE FROM push_batches")

    files = [
        p
        for p in sorted(
            directory.glob("*.xlsx"), key=lambda p: (file_timestamp(p), p.name)
        )
        if not p.name.startswith("~$")
    ]
    total = inserted = updated = skipped = 0
    per_file: list[dict] = []
    for path in files:
        anchor = file_timestamp(path).date()
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            per_file.append({"file": path.name, "rows": 0, "error": str(exc)})
            skipped += 1
            continue
        file_rows = []
        for ws in wb.worksheets:
            file_rows.extend(read_sheet(path, ws))
        wb.close()
        counts = services.upsert_records(
            file_rows,
            source_file=path.name,
            anchor=anchor,
            capture_at=file_timestamp(path).astimezone().isoformat(timespec="seconds"),
        )
        per_file.append(
            {
                "file": path.name,
                "export_time": file_timestamp(path).strftime("%Y-%m-%d %H:%M:%S"),
                "rows": len(file_rows),
                **counts,
            }
        )
        total += len(file_rows)
        inserted += counts["inserted"]
        updated += counts["updated"]
        skipped += counts["skipped"]

    finished = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    batch_id = f"excel-{dt.datetime.now():%Y%m%d_%H%M%S}"
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO import_batches (
                kind, batch_id, source, started_at, finished_at, status,
                total, inserted, updated, skipped
            ) VALUES ('excel', ?, ?, ?, ?, 'success', ?, ?, ?, ?)
            """,
            (
                batch_id,
                str(directory),
                started,
                finished,
                total,
                inserted,
                updated,
                skipped,
            ),
        )
        import_batch_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()[
            "id"
        ]
    return {
        "batch_id": batch_id,
        "import_batch_id": import_batch_id,
        "directory": str(directory),
        "files": len(files),
        "total_rows": total,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "per_file": per_file,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导入物流 Excel 到 SQLite")
    parser.add_argument(
        "--dir",
        default=r"E:\ZY2026\物流单跟踪\output",
        help="物流表目录",
    )
    parser.add_argument("--reset", action="store_true", help="清空旧数据后重新导入")
    args = parser.parse_args()
    result = import_directory(Path(args.dir), reset=args.reset)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
