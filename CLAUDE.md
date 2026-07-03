# AStock — Claude 工作手册

A 股 AI 交易助手，Python 3.11+ CLI，click 命令入口 `astock`。用户是散户，跨 3 个账户
持仓约 85 万，Phase 1 已闭环（持仓/扫描/AI 分析/报告），Phase 2 正在推进。

## 架构地图

```
src/astock/
├── cli.py                 click 命令注册（portfolio / scan / analyze / report / buy / sell）
├── config.py              yaml → dataclass (AppConfig, ScanConfig, AccountConfig)
├── data/
│   ├── http.py            共享 curl_get + retry 装饰器 + SINA_HEADERS
│   ├── cache.py           md5(key).json 文件缓存
│   └── provider.py        get_spot / get_hist / get_industry / get_fund_flow / get_news
├── portfolio/
│   ├── manager.py         build_portfolio + record_trade（改 holdings.yaml）
│   └── models.py          Holding / Position / PortfolioSummary
├── screen/
│   ├── indicators.py      MA / MACD / RSI / KDJ / BOLL / 量比
│   └── scanner.py         全市场拉列表 → 基础过滤 → 打分排序
├── ai/analyst.py          Anthropic SDK 客户端 + 系统提示词 + 上下文构造
└── render/
    ├── tables.py          rich 表格（涨红跌绿）
    └── report.py          Markdown 盘后报告
```

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

## 已知 rough edge / TODO

- `get_fund_flow` / `get_sector_flow` / `get_news` 仍走 akshare，在有代理环境下会失败（有 try/except 兜底返回空 df，不会崩，但数据缺失）。要彻底解决需替换为 curl 直连接口。
- 没有单元测试。
- `record_trade` sell 时不检查 shares 是否足够。

## 使用要求

- 命令一律通过 `.venv/bin/astock` 或 `uv run astock`，不要提示用户全局装。
- 涉及交易（buy/sell）的操作会写 `holdings.yaml`，动手前要确认账户名和代码合法。
- 报告和缓存目录（`data/reports/`、`data/cache/`）都在 `.gitignore` 里，不要 add。
