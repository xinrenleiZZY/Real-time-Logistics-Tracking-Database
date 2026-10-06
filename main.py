"""物流追踪实时库 —— FastAPI 入口

功能：
- 从 E:\\ZY2026\\物流单跟踪\\output 的物流表一次性导入 SQLite（scripts/import_xlsx.py）
- 查询单个/多个 ASIN 的到货时间（预计到港时间 + 14 天）
- 导出全部 [ASIN, 到货时间] 供其他系统入库
- 接收其他系统推送的物流表 JSON（接口格式见 README/接口文档）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from app import db
from app.config import settings
from app.routers import api, ui
from app.services import summary

STATIC_DIR = Path(__file__).resolve().parent / "app" / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("logistics.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_schema()
    logger.info("物流追踪实时库数据库已就绪: %s", settings.db_path)
    yield


app = FastAPI(
    title="物流追踪实时库",
    description=(
        "物流追踪实时库：到货时间 = 预计到港时间 + 14 天。"
        "支持按 ASIN 查询到货时间、全量 [ASIN,time] 导出，"
        "以及接收其他系统推送的物流表 JSON。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)
app.include_router(ui.router)

FALLBACK_HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>物流追踪实时库</title><body><h1>物流追踪实时库</h1>
<p>首页静态文件缺失，接口调试请访问 <a href="/docs">/docs</a>。</p></body></html>"""


@app.get("/", include_in_schema=False)
def index():
    page = STATIC_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return HTMLResponse(FALLBACK_HTML)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "summary": summary()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
