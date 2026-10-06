"""物流追踪实时库 —— 服务管理（启动 / 停止 / 守护 / 自检）。

由 start.bat、stop.bat、状态检查.bat、开机自启 调用。
注意：这里刻意用 Python 而不是 PowerShell 启动子进程，因为 Windows PowerShell 5.1 的
Start-Process 在环境变量同时存在 Path / PATH 时会直接报错，会让守护进程反复启动失败。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "data" / "logs"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
STOP_FILE = ROOT / "data" / "STOP_WATCHDOG"
RUN_SERVER = ROOT / "scripts" / "run_server.py"
DEFAULT_PORT = 7650

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def log(message: str, path: Path = WATCHDOG_LOG) -> None:
    line = "[{0}] {1}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:{0}/healthz".format(port), timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def port_owner_pids(port: int) -> list:
    try:
        completed = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    pids = []
    for raw in completed.stdout.splitlines():
        parts = raw.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(":{0}".format(port)):
            try:
                pid = int(parts[4])
            except ValueError:
                continue
            if pid not in pids:
                pids.append(pid)
    return pids


def local_ipv4() -> list:
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ips.append(sock.getsockname()[0])
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except Exception:
        pass

    def rank(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            try:
                if 16 <= int(ip.split(".")[1]) <= 31:
                    return 2
            except (IndexError, ValueError):
                pass
        return 3

    return sorted(ips, key=rank)


def spawn_watchdog(port: int) -> None:
    base = Path(sys.executable)
    pythonw = base.with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else base
    subprocess.Popen(
        [str(executable), str(Path(__file__).resolve()), "watch", "--port", str(port)],
        cwd=str(ROOT),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def wait_healthy(port: int, seconds: int = 45) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.8)
        if health_ok(port):
            return True
    return False


def open_browser(port: int) -> None:
    try:
        os.startfile("http://localhost:{0}".format(port))
    except Exception:
        pass


def print_urls(port: int) -> None:
    print("  本机   : http://localhost:{0}".format(port))
    for ip in local_ipv4():
        print("  局域网 : http://{0}:{1}".format(ip, port))


def fetch_summary(port: int) -> dict:
    url = "http://127.0.0.1:{0}/api/v1/summary".format(port)
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_start(args: argparse.Namespace) -> int:
    port = args.port
    if not VENV_PY.exists():
        print("未找到虚拟环境：{0}".format(VENV_PY))
        print("请先执行：")
        print("  python -m venv .venv")
        print("  .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1

    if not (ROOT / "data" / "logistics.db").exists():
        print("首次启动：先导入物流表 Excel...")
        subprocess.run(
            [str(VENV_PY), str(ROOT / "scripts" / "import_xlsx.py"), "--dir", r"E:\ZY2026\物流单跟踪\output"],
            cwd=str(ROOT),
        )

    if health_ok(port):
        if not args.quiet:
            print("服务已经在运行：http://localhost:{0}".format(port))
            print_urls(port)
        if args.open_browser:
            open_browser(port)
        return 0

    try:
        STOP_FILE.unlink()
    except OSError:
        pass

    if not args.quiet:
        print("正在后台启动守护进程（端口 {0}）...".format(port))
    spawn_watchdog(port)

    if wait_healthy(port):
        if not args.quiet:
            print("启动成功。")
            print_urls(port)
            print("服务由守护进程托管：进程异常退出会自动重启；停止请双击 stop.bat")
        if args.open_browser:
            open_browser(port)
        return 0

    print("启动超时，请查看日志目录：data\\logs\\")
    return 1


def cmd_watch(args: argparse.Namespace) -> int:
    port = args.port
    python = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    log("守护进程启动（端口 {0}，项目目录 {1}）".format(port, ROOT))

    while True:
        if STOP_FILE.exists():
            try:
                STOP_FILE.unlink()
            except OSError:
                pass
            log("收到停止信号，守护进程退出")
            return 0

        if port_listening(port):
            time.sleep(10)
            continue

        log("启动服务：python scripts\\run_server.py --port {0}".format(port))
        exit_code = -1
        try:
            process = subprocess.Popen([str(python), str(RUN_SERVER), "--port", str(port)], cwd=str(ROOT))
            exit_code = process.wait()
        except Exception as exc:
            log("启动服务失败：{0}".format(exc))

        log("服务已退出（退出码 {0}），{1} 秒后自动重启".format(exit_code, args.restart_delay))
        time.sleep(args.restart_delay)


def cmd_stop(args: argparse.Namespace) -> int:
    port = args.port
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("stop", encoding="utf-8")
    time.sleep(2)

    pids = port_owner_pids(port)
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)

    time.sleep(1)
    if port_listening(port):
        print("端口 {0} 仍在监听，未能完全停止，请稍后重试。".format(port))
        return 1

    print("物流追踪实时库已停止（结束进程 {0} 个，端口 {1} 已释放）。".format(len(pids), port))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    port = args.port
    print("===== 物流追踪实时库 状态自检 =====")
    print("时间        : {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("项目目录    : {0}".format(ROOT))
    print("监听端口    : {0}".format(port))

    listening = port_listening(port)
    print("端口状态    : {0}".format("正在监听（服务进程存在）" if listening else "没有监听（服务未运行）"))
    if listening:
        pids = port_owner_pids(port)
        if pids:
            print("服务进程PID : {0}".format(", ".join(str(p) for p in pids)))
    else:
        print()
        print("服务没有运行，双击 start.bat 即可启动（会自动后台驻留）。")

    healthy = health_ok(port)
    print("健康检查    : {0}".format("正常（/healthz 返回 200）" if healthy else "异常"))

    if healthy:
        try:
            data = fetch_summary(port)["data"]
            print()
            print("----- 数据概览 -----")
            print("物流表历史行数   : {0}".format(data["total_file_rows"]))
            print("当前货件记录数   : {0}".format(data["total_records"]))
            print("有到港/到货时间  : {0}".format(data["records_with_eta"]))
            print("ASIN 数量        : {0}".format(data["distinct_asins"]))
            print("到货时间规则     : 预计到港时间 + {0} 天".format(data["arrival_offset_days"]))
            last_import = data.get("last_import")
            if last_import:
                print("最近一次导入     : {0}（{1}）".format(last_import.get("finished_at"), last_import.get("status")))
            last_push = data.get("last_push")
            print("最近一次推送     : {0}".format(last_push.get("created_at") if last_push else "暂无"))
        except Exception as exc:
            print("读取数据概览失败：{0}".format(exc))

        print()
        print("----- 访问地址 -----")
        print_urls(port)

    print()
    print("----- 守护日志（最近 8 行）-----")
    if WATCHDOG_LOG.exists():
        for line in WATCHDOG_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]:
            print(line)
    else:
        print("（暂无日志，说明还没用 start.bat 启动过）")

    print()
    print("日志目录：data\\logs（server.log = 服务日志，watchdog.log = 守护日志）")
    return 0 if healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="物流追踪实时库 服务管理")
    parser.add_argument("command", choices=["start", "stop", "status", "watch"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--restart-delay", type=int, default=5, help="服务退出后多少秒重启（watch 用）")
    parser.add_argument("--quiet", action="store_true", help="安静模式，不打印过程信息（开机自启用）")
    parser.add_argument("--open-browser", action="store_true", help="启动成功后打开浏览器")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handlers = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "watch": cmd_watch,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
