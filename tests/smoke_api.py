"""本地冒烟测试：启动 uvicorn main:app 后执行 python tests/smoke_api.py"""

from __future__ import annotations

import json
import sys
import uuid
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7650"


def call(method: str, path: str, body=None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    summary = call("GET", "/api/v1/summary")["data"]
    print("summary:", summary["total_records"], summary["records_with_eta"], summary["distinct_asins"])

    found = call("GET", "/api/v1/arrival/query?asins=B08DNLTQQ3")["data"]
    latest = [x for x in found["items"] if x["shipment_id"] == "FBA19N96FNV7"]
    assert latest, "未找到测试货件 FBA19N96FNV7"
    assert latest[0]["eta_date"] == "2026-09-13"
    assert latest[0]["arrival_date"] == "2026-09-27"
    print("query ok:", latest[0]["asin"], latest[0]["arrival_date"])

    post = call(
        "POST",
        "/api/v1/arrival/query",
        {"asins": ["B08DNLTQQ3", "B0H5VPQMN3"]},
    )["data"]
    assert post["total"] >= found["total"]
    assert {x["asin"] for x in post["items"]} == {"B08DNLTQQ3", "B0H5VPQMN3"}
    print("post query ok:", post["total"])

    export = call("GET", "/api/v1/arrival/export?earliest_only=true")["data"]
    print("export ok:", export["total"])

    push_body = {
        "source": "smoke-test",
        "push_id": "smoke-" + str(uuid.uuid4()),
        "table_name": "物流跟踪表",
        "data_date": "2026-09-08",
        "records": [
            {
                "品名": "90shine-JI-万圣节涂色本60本23版",
                "ASIN": "B08DNLTQQ3",
                "货件单号": "FBA19N96FNV7",
                "发货量": 117,
                "物流渠道": "义乌-积米极致达",
                "跟踪编号": "",
                "开船时间": "2026-09-03",
                "预计到港时间": "2026-09-13",
                "是否查验": "否",
            }
        ],
    }
    pushed = call("POST", "/api/v1/records/push", push_body)
    assert pushed["code"] == 0
    assert pushed["data"]["updated"] == 1
    assert pushed["message"] == "修改更新成功"
    print("push ok:", pushed["data"])

    again = call("POST", "/api/v1/records/push", push_body)
    assert again["data"]["duplicated"] is True
    print("push idempotent ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
