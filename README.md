# AStock

[![tests](https://github.com/gutswp/astock/actions/workflows/test.yml/badge.svg)](https://github.com/gutswp/astock/actions/workflows/test.yml)

A 股散户的个人化 AI 交易助手。跨账户合并持仓、全市场技术面扫描、Claude 驱动的个股分析和盘后报告。

## 快速开始

```bash
# 1. 依赖（Python 3.11+，用 uv 最省事）
uv venv --python 3.11
uv pip install -e .

# 2. 配置 .env
cat > .env <<'EOF'
ANTHROPIC_BASE_URL=https://model.sudorouter.ai   # 可选：走 Claude 代理网关
ANTHROPIC_AUTH_TOKEN=sk-xxx                       # 或 ANTHROPIC_API_KEY
EOF

# 3. 填持仓（config/holdings.yaml 已给出模板结构）
```

## Web UI（推荐）

```bash
astock web              # 启动，默认 http://127.0.0.1:8712
astock web -p 8080      # 换端口
astock web --reload     # 开发模式，改代码/模板自动重载
```

Web UI 包含所有 CLI 能力，仪表盘 = 持仓 + 大盘 + 行业 + 一键 AI 决策。

后台预警守护（可选）：在 `config/settings.yaml` 里把 `alert_daemon.enabled` 改 `true`，
web 起来后会按 interval 定时跑关注池，触发时走 `notify:` 配置的通道推送（Server 酱 / 邮件）。

## Shell completion（可选）

在 zsh 里 tab 补全账户名 / 股票代码 / alert 类型：

```zsh
# ~/.zshrc
eval "$(_ASTOCK_COMPLETE=zsh_source astock)"
```

bash 同理，把 `zsh_source` 换成 `bash_source`。

## 命令（CLI）

| 命令 | 用途 |
|------|------|
| `astock web` | 启动 Web UI |
| `astock portfolio` | 跨账户合并持仓表（现价/盈亏/行业分布） |
| `astock scan [--top N]` | 全市场机会扫描，按技术信号打分排序 |
| `astock analyze <code>` | Claude AI 深度分析单只股票（含持仓上下文） |
| `astock advise` | AI 决策报告：整合大盘+持仓+机会池给操作清单 |
| `astock review [-d N]` | AI 复盘：从交易日志找模式与归因 |
| `astock journal [-c code] [-a acct] [-d N]` | 查看交易历史 |
| `astock alert list/add/rm` | 关注池 & 预警规则 CRUD |
| `astock watch [--interval N]` | 单次/循环扫描关注池，触发时通知 |
| `astock report` | 生成 Markdown 盘后报告到 `data/reports/` |
| `astock buy/sell <code> <shares> <price> -a <acct> [-n "备注"]` | 记录交易 |

## 分析工具

- `/tools/sizing` —— 基于止损位反推建议手数（风险控制）
- `/tools/backtest` —— MACD 金叉 / RSI 超卖 / MA20/60 突破 / KDJ 金叉 的历史胜率回测

## 数据源

- **实时行情**：新浪 `hq.sinajs.cn`（gbk 编码，`_curl_get` 直连绕开系统代理）
- **日线**：新浪 `money.finance.sina.com.cn/quotes_service/api`
- **全市场列表**：新浪 `Market_Center.getHQNodeData` 分页，兜底 AKShare
- **行业分类**：`push2delay.eastmoney.com`（curl 直连，7 天缓存）
- **资金流 / 板块 / 新闻**：AKShare

> 若本机开着代理（Clash / v2ray 等），`requests` 会自动读系统代理，可能导致
> eastmoney/akshare 拉取失败。项目里所有实时行情走 `curl` 是刻意为之——
> curl 不受系统代理影响。

## 技术指标（scanner）

- MA5/10/20/60 突破
- MACD 金叉
- RSI 超卖反弹（14 日）
- KDJ 金叉（K 在 50 以下时权重更高）
- 布林带下轨反弹
- 量比（默认 ≥ 2.0）

## 配置

- `config/holdings.yaml`：账户 → 持仓明细（code / name / shares / cost）
- `config/settings.yaml`：扫描阈值、AI 模型、缓存 TTL

## 缓存

`data/cache/` 下按 md5(key) 存 JSON，TTL：spot 60s / hist 1d / industry 7d。
`data/reports/` 是 `report` 命令的产出目录。两者都在 `.gitignore` 里。
