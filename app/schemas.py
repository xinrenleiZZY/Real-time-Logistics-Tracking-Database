"""API 请求模型"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

MAX_ASINS = 200
MAX_PUSH_RECORDS = 20000


def normalize_asin(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError("ASIN 不能为空")
    return text


class AsinQuery(BaseModel):
    """POST 查询：支持单个或多个 ASIN"""

    asins: List[str] = Field(min_length=1, max_length=MAX_ASINS)

    @field_validator("asins")
    @classmethod
    def _norm(cls, value: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for raw in value:
            text = normalize_asin(raw)
            if text not in seen:
                seen.add(text)
                out.append(text)
        if not out:
            raise ValueError("asins 不能为空")
        return out


class PushRecord(BaseModel):
    """推送记录：JSON 使用中文表头作为主字段，兼容英文别名"""

    model_config = {"extra": "ignore"}

    品名: Optional[Any] = None
    product_name: Optional[Any] = None
    ASIN: Optional[Any] = None
    asin: Optional[Any] = None
    货件单号: Optional[Any] = None
    shipment_id: Optional[Any] = None
    发货量: Optional[Any] = None
    quantity: Optional[Any] = None
    物流渠道: Optional[Any] = None
    channel: Optional[Any] = None
    跟踪编号: Optional[Any] = None
    tracking_numbers: Optional[Any] = None
    开船时间: Optional[Any] = None
    sailing_date: Optional[Any] = None
    预计到港时间: Optional[Any] = None
    eta_date: Optional[Any] = None
    是否查验: Optional[Any] = None
    inspection: Optional[Any] = None

    def normalized(self) -> Dict[str, Optional[str]]:
        def pick(chinese: Optional[Any], english: Optional[Any]) -> Optional[str]:
            if chinese is not None and str(chinese).strip() != "":
                return str(chinese).strip()
            if english is not None and str(english).strip() != "":
                return str(english).strip()
            return None

        return {
            "product_name": pick(self.品名, self.product_name) or "",
            "asin": str(pick(self.ASIN, self.asin) or "").strip().upper(),
            "shipment_id": pick(self.货件单号, self.shipment_id) or "",
            "quantity": pick(self.发货量, self.quantity) or "",
            "channel": pick(self.物流渠道, self.channel) or "",
            "tracking_numbers": pick(self.跟踪编号, self.tracking_numbers) or "",
            "sailing_date": pick(self.开船时间, self.sailing_date),
            "eta_date": pick(self.预计到港时间, self.eta_date),
            "inspection": pick(self.是否查验, self.inspection) or "",
        }


class PushBatch(BaseModel):
    """JSON 推送请求

    {
      "source": "来源系统标识（必填）",
      "push_id": "外部批次号（可选，重复推送自动幂等）",
      "table_name": "物流跟踪表 / 未开船物流表 / 货件号重查物流表（可选）",
      "data_date": "2026-09-08（可选，用于给不带年份的日期补年份）",
      "records": [ { ...表格字段... } ]
    }
    """

    source: str = Field(min_length=1, max_length=100)
    push_id: Optional[str] = Field(default=None, max_length=100)
    table_name: Optional[str] = Field(default=None, max_length=100)
    data_date: Optional[str] = None
    records: List[PushRecord] = Field(min_length=1, max_length=MAX_PUSH_RECORDS)
