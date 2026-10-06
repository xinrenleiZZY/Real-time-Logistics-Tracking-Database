"""日期解析：兼容表格里 M/D、YYYY-MM-DD、YYYY/M/D、9月13日 等写法

Excel 表里的“预计到港时间”大多不带年份（例如 9/13），解析时会以
“数据文件导出时间/推送日期”为锚点，选择离锚点最近的自然年份。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from app.config import settings

_EXPLICIT_YEAR = re.compile(
    r"^\s*(?P<y>\d{4})\s*[年/\-.年]\s*(?P<m>\d{1,2})\s*[月/\-.]\s*(?P<d>\d{1,2})\s*(?:日)?\s*$"
)
_YEARLESS = re.compile(
    r"^\s*(?P<m>\d{1,2})\s*[月/\-.]\s*(?P<d>\d{1,2})\s*(?:日)?\s*$"
)


def _as_date(value, anchor: Optional[dt.date]) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        # Excel 序列日期
        if 20000 <= float(value) <= 80000:
            try:
                return dt.date(1899, 12, 30) + dt.timedelta(days=float(value))
            except (OverflowError, ValueError):
                return None
        return None
    if not isinstance(value, str):
        return None
    text = str(value).strip()
    if not text:
        return None
    # 兼容 "2026-09-13 00:00:00" 这类带时间文本
    if len(text) >= 10:
        try:
            return dt.date.fromisoformat(text[:10])
        except ValueError:
            pass
    m = _EXPLICIT_YEAR.match(text)
    if m:
        try:
            return dt.date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
    m = _YEARLESS.match(text)
    if not m:
        return None
    month = int(m.group("m"))
    day = int(m.group("d"))
    anchor = anchor or dt.date.today()
    candidates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidates.append(dt.date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - anchor).days))


def parse_date(value, anchor: Optional[dt.date] = None) -> Optional[dt.date]:
    return _as_date(value, anchor)


def to_iso(value, anchor: Optional[dt.date] = None) -> Optional[str]:
    parsed = parse_date(value, anchor)
    return parsed.isoformat() if parsed else None


def arrival_date(eta_iso: Optional[str]) -> Optional[str]:
    if not eta_iso:
        return None
    try:
        eta = dt.date.fromisoformat(eta_iso)
    except ValueError:
        return None
    return (eta + dt.timedelta(days=settings.arrival_offset_days)).isoformat()
