# AStock — Claude 工作手册

A 股 AI 交易助手，Python 3.11+ CLI，click 命令入口 `astock`。用户是散户，跨 3 个账户
持仓约 85 万，Phase 1 已闭环（持仓/扫描/AI 分析/报告），Phase 2 正在推进。

## 架构地图

```
src/astock/
├── cli.py                 click 命令注册（portfolio/scan/analyze/advise/review/
│                          journal/alert/watch/buy/sell/report/web）
├── config.py              yaml → dataclass (AppConfig, ScanConfig, AccountConfig)
├── data/
│   ├── http.py            共享 curl_get + retry 装饰器 + SINA_HEADERS
│   ├── cache.py           md5(key).json 文件缓存
│   └── provider.py        get_spot / get_hist / get_industry / get_indices / ...
├── portfolio/
│   ├── manager.py         build_portfolio + record_trade（改 holdings.yaml）
│   ├── journal.py         data/trades.jsonl append + load
│   └── models.py          Holding / Position / PortfolioSummary
├── screen/
│   ├── indicators.py      MA / MACD / RSI / KDJ / BOLL / 量比
│   ├── scanner.py         全市场拉列表 → 基础过滤 → 打分排序（支持 progress_cb）
│   ├── alerts.py          watchlist.yaml CRUD + 7 种触发类型判定
│   └── watcher.py         循环扫描 + macOS 桌面通知
├── ai/
│   ├── client.py          make_client + _load_env（支持 AUTH_TOKEN / BASE_URL）
│   ├── analyst.py         单股分析（generate_analysis + run CLI）
│   ├── advisor.py         AI 决策报告（generate_advise + run CLI）
│   └── reviewer.py        AI 复盘（generate_review + run CLI）
├── render/
│   ├── tables.py          rich 表格（涨红跌绿）
│   └── report.py          Markdown 盘后报告
└── web/                   FastAPI + Jinja2 + HTMX + Tailwind
    ├── app.py             FastAPI 装配，state.config, state.templates
    ├── deps.py            render() 包装 TemplateResponse（starlette 新 API）
    ├── routes/            dashboard/ai/trade/journal/scan/alerts 六个模块
    ├── templates/         base.html + 每页 + partials/
    └── static/            （CDN 加载，暂无本地静态资源）
```

## Web UI

`astock web` → uvicorn 起 FastAPI，默认 `127.0.0.1:8712`。前端全部 CDN（Tailwind
+ HTMX + htmx-ext-sse），无前端构建步骤。所有 route 都用 `render(request, tpl, **ctx)`
包装 starlette 1.3+ 的新 `TemplateResponse(request, name, ctx)` API。

**长任务模式（scan）**：POST `/scan/start` 起线程 + 返回 job_id，模板里
`hx-get="/scan/status/{id}" hx-trigger="every 2s"` 自动轮询直到状态变 done。
_JOBS 是 in-memory dict，进程重启就丢；对于本地单用户场景足够。

**AI 长阻塞（advise/review/analyze）**：`starlette.concurrency.run_in_threadpool`
调 sync 生成函数（Anthropic SDK sync），HTMX 按钮 hx-disabled-elt + htmx-indicator
显示"生成中…"。约 30–60s。

**行情自刷新**：`/partials/kpi`、`/partials/portfolio` 通过 HTMX
`hx-trigger="every 60s"` 每 60 秒局部替换，无需整页刷新。

**表单更新持仓**：POST `/trade` 后 `request.app.state.config = load_config()` 强制
重新加载 holdings.yaml，保证 dashboard 立即看到新数据。

## 关键约定

- **HTTP 一律走 `curl_get`**（`data/http.py`），不用 `requests`。原因：本地开发环境常
  开 Clash 代理，`requests` 会自动读系统代理，AKShare 之类的库因此无法直连 eastmoney。
  curl 不受影响。任何新增数据源都应该沿用 `curl_get`。
- **eastmoney 用 `push2delay.eastmoney.com`**，不是 `push2.eastmoney.com`。后者从我们
  这条网络会 empty-reply（连 UA/Referer 都改过不管用），delay 域名镜像同样字段。
- **单位**：新浪的 `总市值` 单位是"万元"；akshare `stock_zh_a_spot_em` 的 `总市值` 是
  "元"。scanner 里的 min_market_cap 阈值以"亿元"为单位。三者互转要小心。
- **代码判交易所**：`6/9` → sh、`0/2/3` → sz、ETF `5xx` → sh、ETF `1xx` → sz。
  见 `provider._code_to_sina` 和 `provider._em_secid`。
- **打分**：`len(signals) * 20`，MACD +15，突破 60 日线 +10，RSI+BOLL 双确认 +10，
  KDJ 与 RSI/BOLL 任一联动 +5，封顶 100。见 `screen/scanner.py:run_scan`。
- **缓存 TTL**：spot 60s / hist 1 天 / industry 7 天 / sector_flow 5 分钟。

## AI 客户端

`ai/analyst.py::_make_client` 支持三个环境变量：
- `ANTHROPIC_API_KEY`（x-api-key 头）
- `ANTHROPIC_AUTH_TOKEN`（Authorization: Bearer 头，用于 sudorouter 等网关）
- `ANTHROPIC_BASE_URL`（代理网关 URL）

.env 文件在项目根，由 `_load_env()` 手工加载（未用 python-dotenv）。默认模型
`claude-sonnet-4-6`，见 `settings.yaml::ai.model`。

## 常见任务速查

- 加新技术指标：`screen/indicators.py` 加计算函数 + detect 函数，`screen/scanner.py::_scan_stock` 里 wire，`config.py::ScanConfig` 加开关，`settings.yaml::scan.signals` 加默认值。
- 加新数据源：优先走 curl；样例见 `data/provider.py::get_industry`（curl + json 解析 + 7 天缓存）。
- 加新 CLI 命令：`cli.py` 装饰 `@cli.command()`，把配置从 `ctx.obj["config"]` 取。
- 加新报告字段：改 `render/report.py::generate_report` 生成 Markdown，或 `render/tables.py` 加 rich 表格。

## Phase 5 新增

- `tools/sizing.py` + `tools/backtest.py`：基于止损位的仓位建议 / 信号回测
- `notify/{serverchan,mail,dispatch}.py`：Server 酱 / SMTP 推送通道
- `screen/daemon.py`：随 web 启动的后台预警守护，dedup + 落 `data/alerts.log`
- `web/routes/{api,export,tools}.py`：JSON 联动 / K 线数据 / CSV 导出 / 仓位/回测页
- `tests/`：indicators / journal / alerts / sizing / backtest 单测 32 条
- `data/http.py::_throttle`：按 host 最小间隔的简单节流
- `data/provider.py`：get_fund_flow / get_sector_flow / get_news 全部改用 curl 直连
  eastmoney（`push2delay` / `search-api-web`），彻底脱离 requests 走系统代理的问题
- Web UI 移动端 responsive（grid-cols-1 md:grid-cols-N + 表格横向滚动）
- ScanJob 持久化到 `data/scan_jobs.jsonl`，重启保留最近 20 条
- Click shell completion：账户名 / 已知代码 / alert 类型

## 使用要求

- 命令一律通过 `.venv/bin/astock` 或 `uv run astock`，不要提示用户全局装。
- 涉及交易（buy/sell）的操作会写 `holdings.yaml`，动手前要确认账户名和代码合法。
- 报告和缓存目录（`data/reports/`、`data/cache/`）都在 `.gitignore` 里，不要 add。
