# 物流追踪实时库

参照“UPC 使用情况实时库”做的一个精简版实时库：把物流单跟踪产出的 Excel 一次性导入 SQLite，
对外提供 ASIN 到货时间查询、全量 `[ASIN, 到货时间]` 导出，以及接收其他电脑项目推送的物流表 JSON。

## 功能

| 功能 | 说明 |
| --- | --- |
| 一次性导入 | 读取 `E:\ZY2026\物流单跟踪\output` 下全部物流 Excel（跳过 `~$` 临时文件）；每一张表的每一行都追加到历史表不覆盖，同时按 `货件单号 + ASIN` 维护一份最新快照用于计算到货时间 |
| 到货时间规则 | 到货时间 = 预计到港时间 + 14 天（固定 14，可用 `ARRIVAL_OFFSET_DAYS` 调整） |
| 按 ASIN 查询 | `GET/POST /api/v1/arrival/query`，一次查单个或多个 ASIN |
| 全量同步 | `GET /api/v1/arrival/export` 返回全部 `[ASIN, time]`，其他系统可直接入库；`earliest_only=true` 时每个 ASIN 只返回最早一条，`upcoming_only=true` 只看今天及之后到货 |
| JSON 推送 | `POST /api/v1/records/push`，其他电脑的项目把表格数据转成 JSON 推送到本系统，返回“修改更新成功”，重复 `push_id` 自动幂等 |
| 物流表数据查询 | 网页可按 ASIN/货件单号/品名/渠道/到港时间/来源文件筛选全部物流表原始行（同一天重复文件也保留），分页查看并导出 CSV |
| 可选令牌 | `API_TOKEN` / `PUSH_TOKEN` 配置后分别校验 `X-API-Token` / `X-Push-Token` |

> 通行证与审核（按 UPC 模式保留）将在你提供“其他系统”的接入对象后按实际流程接通，接口对象先不臆造。

## 项目结构

```
物流追踪实时库/
├── main.py                  # FastAPI 入口
├── start.bat                # 启停/自启/自检脚本（后台运行 + 守护重启）
├── stop.bat
├── 状态检查.bat
├── 开机自启_安装.bat / 开机自启_卸载.bat
├── 防火墙放行7650.bat
├── requirements.txt
├── .env.example             # 配置样例
├── app/
│   ├── config.py            # 环境配置
│   ├── db.py                # SQLite 建表与访问
│   ├── dates.py             # M/D、YYYY-MM-DD 等日期解析与 +14 天计算
│   ├── schemas.py           # API 请求模型
│   ├── services.py          # 入库/查询/导出核心
│   └── routers/api.py       # /api/v1 开放接口
├── scripts/
│   ├── import_xlsx.py       # 一次性导入 Excel
│   ├── service.py           # 服务管理：启动 / 停止 / 守护 / 状态自检
│   ├── run_server.py        # 后台服务启动器（日志写入 data/logs/server.log）
│   └── windows/             # 开机自启、防火墙放行等 Windows 辅助脚本
├── tests/
│   └── smoke_api.py         # 本地冒烟测试
├── data/logistics.db        # SQLite 数据库（自动生成，已导入）
└── data/logs/               # 运行日志（自动生成）
```

## 快速开始

### 1. 安装依赖（首次）

```powershell
cd "E:\ZY2026\物流追踪实时库"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 一次性导入物流表

```powershell
.\.venv\Scripts\python.exe scripts\import_xlsx.py --dir "E:\ZY2026\物流单跟踪\output"
```

导入规则：

- 处理目录下所有 `*.xlsx`，按文件名里的导出时间从旧到新合并；
- 每张表每一行都会追加到“物流表历史”（`logistics_history`），同一天/重复文件的行不覆盖、不丢失；
- 同时维护当前快照表（唯一键 `货件单号 + ASIN`，重复记录以最新文件为准），到货时间查询和 `[ASIN,time]` 导出基于最新快照，避免重复货件算重；
- 预计到港时间为空/解析失败的行不产出到货时间；
- 不带年份的日期（如 `9/13`）按“距离该文件导出时间最近的自然年份”补全年份；
- 如需全量重导：`--reset` 会先清空当前快照与历史再导入。

### 3. 启动服务

直接**双击 `start.bat`** 即可（推荐日常使用）：

- 服务在后台运行，关掉命令行窗口不影响；
- 由守护进程托管，进程意外退出会在 5 秒内自动重启；
- 会自动打开浏览器，并在窗口里打印本机和局域网访问地址。

- 功能网页（导航页签：ASIN 到货查询 / 物流表查询 / 全量导出 / 记录，支持深浅主题）：<http://localhost:7650>
- 在线调试（Swagger）：<http://localhost:7650/docs>
- 健康检查：<http://localhost:7650/healthz>

停止服务：双击 `stop.bat`。查看运行状态与数据概览：双击 `状态检查.bat`。

其他电脑调用时，把 `localhost` 换成运行本服务的电脑局域网 IP（例如 `192.168.0.193`）。

### 4. 保持服务一直可用（重要）

之前“页面突然打不开”基本都是同一类原因：**服务进程没在运行**（电脑重启、注销登录、命令行窗口被关掉、进程被杀），
而不是数据或接口坏了。现在提供了三重保障：

| 脚本 | 作用 |
| --- | --- |
| `start.bat` | 后台启动 + 守护进程自动重启（日常启动用这个） |
| `开机自启_安装.bat` | 开机登录后自动在后台启动，**只需双击一次**；取消用 `开机自启_卸载.bat` |
| `防火墙放行7650.bat` | 放行入站 7650 端口，让局域网其他电脑能访问（会弹管理员授权窗口） |
| `状态检查.bat` | 一键自检：是否在跑、健康检查、数据条数、局域网地址、最近日志 |

排查“访问不了”的固定顺序：

1. 双击 `状态检查.bat`，看“端口状态 / 健康检查”；
2. 若显示没有监听，双击 `start.bat` 即可恢复；
3. 若本机能开、别的电脑打不开，双击 `防火墙放行7650.bat`（需要管理员权限）并确认两台电脑在同一网段；
4. 仍异常时，把 `data\logs\` 目录里的 `server.log` 和 `watchdog.log` 发出来定位。

运行日志：`data\logs\watchdog.log`（启停/重启记录）、`data\logs\server.log`（服务运行日志，5MB 自动轮转保留 5 份）。

> 服务启停刻意用 Python 而不是 PowerShell 实现：这台电脑的环境变量里同时存在 `Path` 与 `PATH`，
> Windows PowerShell 5.1 的 `Start-Process` 遇到这种环境会直接报错（“已添加项。字典中的关键字:Path”），
> 曾导致守护进程反复启动失败、页面打不开。改用 Python 的 `subprocess` 后已不受影响。

> 如果希望“不登录 Windows 也能自动运行”，需要用管理员身份把 `start.bat` 注册成“计算机启动时”的计划任务；默认提供的开机自启是登录后运行，已能满足日常使用。

### 5. 配置（可选）

复制 `.env.example` 为 `.env` 后修改：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_HOST` | `0.0.0.0` | 监听地址 |
| `APP_PORT` | `7650` | 监听端口 |
| `LOGISTICS_DB_PATH` | `data/logistics.db` | SQLite 文件路径 |
| `ARRIVAL_OFFSET_DAYS` | `14` | 到货时间 = 预计到港 + 该天数 |
| `API_TOKEN` | 空 | 配置后 `/api/v1` 需 `X-API-Token` |
| `PUSH_TOKEN` | 空 | 配置后推送需 `X-Push-Token` |

## 后续增量更新

后续其他电脑的项目不需要再人工导入 Excel，直接把表格数据转成 JSON 推送到本系统即可：

```bash
curl -X POST "http://<本机IP>:7650/api/v1/records/push" \
  -H "Content-Type: application/json" \
  -d @push.json
```

JSON 结构（字段名与 Excel 表头一致，可同时带英文别名）：

```json
{
  "source": "物流单跟踪-上海电脑",
  "push_id": "20260908_001",
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
      "是否查验": "否"
    }
  ]
}
```

- `source`：必填，来源系统标识；
- `push_id`：可选，同一来源同一 push_id 重复推送会被忽略（幂等）；
- `data_date`：可选，用于给不带年份的日期补年份；
- `records`：至少 1 条，每条必须包含 `ASIN` 和 `货件单号`，其余字段缺省补空。

完整接口与示例见同目录《物流追踪实时库接口文档.md》。
