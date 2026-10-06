"""后台服务启动器：由守护进程（scripts/service.py watch）调用。

统一把 uvicorn 日志写到 data/logs/server.log（自动轮转），
避免依赖 Windows 侧的输出重定向（cmd / PowerShell 环境差异会导致启动失败）。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

LOG_DIR = BASE_DIR / "data" / "logs"
LOG_FILE = LOG_DIR / "server.log"


def _resolve_port() -> int:
    """命令行 --port 优先，其次读配置（APP_PORT / 默认 7650）。"""
    argv = sys.argv[1:]
    for index, value in enumerate(argv):
        if value in ("--port", "-p") and index + 1 < len(argv):
            try:
                return int(argv[index + 1])
            except (TypeError, ValueError):
                break
    from app.config import settings

    return settings.app_port


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def main() -> int:
    _setup_logging()
    logger = logging.getLogger("logistics.run")
    try:
        import uvicorn

        from app.config import settings

        port = _resolve_port()
        logger.info("物流追踪实时库准备监听 %s:%s", settings.app_host, port)
        uvicorn.run(
            "main:app",
            host=settings.app_host,
            port=port,
            reload=False,
            log_config=None,
        )
        logger.info("服务已退出")
        return 0
    except KeyboardInterrupt:
        logger.info("收到中断信号，服务退出")
        return 0
    except Exception:
        logger.error("服务启动失败：\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
