# AStock 使用手册

AStock 是给 A 股散户的个人化 AI 交易助手。这份手册按"用起来"的顺序讲，不是按功能罗列。

---

## 目录

1. [首次配置](#1-首次配置)
2. [启动方式](#2-启动方式)
3. [日常工作流（推荐路径）](#3-日常工作流推荐路径)
4. [Web UI 每个页面](#4-web-ui-每个页面)
5. [CLI 命令一览](#5-cli-命令一览)
6. [配置文件详解](#6-配置文件详解)
7. [推送与预警](#7-推送与预警)
8. [数据源与缓存](#8-数据源与缓存)
9. [常见问题](#9-常见问题)

---

## 1. 首次配置

### 1.1 装依赖

```bash
uv venv --python 3.11
uv pip install -e .
```

### 1.2 `.env`（放项目根目录，会被 gitignore）

```
ANTHROPIC_BASE_URL=https://model.sudorouter.ai
ANTHROPIC_AUTH_TOKEN=sk-xxxxxxxxxxxxxxxxxxxxxxx
# 或用 ANTHROPIC_API_KEY，两者取其一
```

如果你机器上开着系统代理（Clash / v2ray），可以额外加：

```
NO_PROXY=*
```

避免 requests 走系统代理把 akshare 拉挂。curl 直连的接口（sina/eastmoney 大部分）不受影响。

### 1.3 `config/holdings.yaml`

按下面结构填你的实际持仓。`shares` 是股数，`cost` 是持仓均价（元）：

```yaml
accounts:
  - name: wp-ky              # 账户内部标识，随便起
    broker: 开源证券
    holdings:
      - {code: '000063', name: 中兴通讯,  shares: 5000, cost: 43.541}
      - {code: '512660', name: 军工ETF,   shares: 32000, cost: 1.564}
  - name: ymj-gtht
    broker: 国泰海通
    holdings:
      - {code: '600519', name: 贵州茅台,   shares: 100,  cost: 1580.0}
```

后续新买卖不用手写 —— 用 CLI `astock buy/sell` 或 Web 的 `/trade` 表单自动回写。

### 1.4 `config/watchlist.yaml`（可选）

关注池默认空。用 CLI `astock alert add` 或 Web 的 `/alerts` 加规则。

---

## 2. 启动方式

### Web UI（推荐日常用）

```bash
astock web                    # 默认 http://127.0.0.1:8712
astock web -p 8080            # 换端口
astock web --reload           # 开发模式，改模板/代码自动重启
```

打开浏览器进 `http://127.0.0.1:8712`。

### CLI（脚本、cron、终端习惯者）

所有 web 功能都有对应 CLI。见 [第 5 节](#5-cli-命令一览)。

### Shell completion（可选）

zsh：

```zsh
# ~/.zshrc
eval "$(_ASTOCK_COMPLETE=zsh_source astock)"
```

之后 `astock buy 002<TAB>` 会补出你持仓里的代码，`-a <TAB>` 补账户名。

---

## 3. 日常工作流（推荐路径）

### 早盘前（9:00 之前）

1. `/` 仪表盘 —— 看昨日持仓 + 大盘指数状态，脑子先"通电"
2. `/advise` 点「立即生成」—— AI 综合决策报告，30-60s 出，边生成边看
   - 输入：大盘 + 板块资金流 + 你的持仓 + 昨日 scan Top
   - 输出：整体仓位建议 + 逐股操作清单（清仓/减仓/持有/试仓）+ 风险提示
   - 报告自动落 `data/reports/YYYY-MM-DD.advise.md`，右侧「历史报告」可回看
3. 如果开了后台守护 + 推送，AI 决策会自动推到 Server 酱

### 盘中（10:00 - 15:00）

- **持仓表 60s 自刷**，涨跌颜色一眼看
- 想深挖某只 → 表格里点「分析」→ K 线（4MA + BOLL 通道 + SAR + 成交量）+ AI 分析（有当日缓存直接显示，右上「重新生成 ↻」强刷）
- 想批量分析持仓 → 持仓表头右侧「批量 AI 分析 →」
- **预警**：`astock watch --interval 60` 或后台 daemon 自动跑，触发 macOS 弹窗 + Server 酱/邮件

### 盘后（15:00 - 收盘后）

1. `/scan` 全市场扫描机会 —— 29s 出结果，色阶分数排序
2. 从 scan 结果点「AI 分析 →」，验证信号
3. 想验证策略普适性 → `/tools/backtest/batch` 拿一篮子跑同一策略
4. 想找当前形态的最佳参数 → `/tools/optimize` 网格搜索
5. 算仓位 → 每行「→ 凯利」直连 `/tools/sizing?mode=kelly`
6. `/trade` 记录当日交易，`--note` 写清楚"什么信号什么价位"
7. `/review` 定期 AI 复盘（周或月）

### 周末

- `/review` 回看 30/90 天，AI 找模式："你在没写 note 的交易上 100% 亏钱"
- `/tools/optimize` 对本周挂着的候选跑参数网格，为下周计划做准备

---

## 4. Web UI 每个页面

### 4.1 `/` 仪表盘

- **4 KPI**：总市值 / 浮动盈亏 / 今日盈亏（按持仓×日涨跌加权）/ 持仓+账户数
- **持仓明细表**：60s 自动刷新，点击表头排序（数值和文本两种）；右上有「导出 CSV」
- **大盘指数**：上证 / 深证 / 创业板 / 沪深300 / 科创50
- **行业分布**：按市值加权，横向条形图
- **今日 AI 决策**：跳 `/advise` 一键触发
- **最近交易**：底部 5 条预览，「+ 记一笔」直连 `/trade`

### 4.2 `/scan` 机会扫描

- 全市场 4700+ 只，过滤条件：涨幅 1-8% + 成交额 > 1 亿
- 技术信号：MACD 金叉 / MA5/10/20/60 突破 / RSI 超卖反弹 / KDJ 金叉 / BOLL 下轨反弹 / 量比 ≥ 2 / (可开) CCI / DMI / SAR
- 打分 = 信号数 × 20 + MACD +15 + 突破 60 日线 +10 + 反转双确认 +10 + (可开) 板块动能加分
- 后台线程运行，进度条每 2s 刷新，中途可点「取消」保留部分结果
- 结果表每行点「AI 分析 →」跳单股页
- 右上「导出 CSV」

### 4.3 `/advise` AI 决策报告

- 点「立即生成」触发 SSE 流式生成，边生成边渲染 markdown
- 完成后右上角 ✓ + 保存文件名提示
- 右侧「历史报告」列表点击加载对应日期的报告
- 如果 `notify.push_ai_reports.advise = true`，完成后自动推 Server 酱/邮件

### 4.4 `/review` AI 复盘

- 选「回看 N 天」（默认 90）
- 从 `data/trades.jsonl` 读交易，AI 分析归因、模式、给改进建议
- 需要至少几笔带 note 的交易才有意义

### 4.5 `/analyze/{code}` 单股深度页

- **K 线**：ECharts 蜡烛（红涨绿跌）+ MA5/10/20/60 + BOLL 通道（虚线）+ SAR 三角
  - 图例点击开关，BOLL/SAR 默认关，需要时点亮
  - 底部时间轴滑块，可缩放查看
- **AI 分析**：SSE 流式，5 段（现状/技术面/消息面/风险/操作建议）
  - **同一天有缓存直接显示**，右上「重新生成 ↻」强刷
  - 缓存文件 `data/reports/YYYY-MM-DD.analyze.{code}.md`

### 4.6 `/analyze` 批量 AI 分析

- 从持仓多选 + 手填代码，最多 8 只
- 结果页并行 SSE，每张卡独立完成
- 命中缓存的秒开

### 4.7 `/trade` 记录交易

- 买入 / 卖出单选 · 账户下拉 · 代码（输入即联动名称+现价）· 数量 · 价格 · 备注
- 提交后同步 `holdings.yaml`（改结构）+ `data/trades.jsonl`（append）
- 已有持仓合并加权成本；新代码自动查名称

### 4.8 `/journal` 交易日志

- 代码 / 账户 / 天数三重过滤
- 每行显示交易变动前后持仓状态
- 「记一笔」+「导出 CSV」在右上

### 4.9 `/alerts` 预警管理

- 关注池 CRUD：加 / 删规则、整只移除
- 7 种规则类型：
  - `price_above` / `price_below`：达到某价
  - `stop_loss`：跌破止损
  - `change_above` / `change_below`：当日涨跌超阈值
  - `ma_break` + `period`：上穿 / 跌破某均线
  - `macd_cross`：金叉 / 死叉
- 「立即扫描」按钮：单次运行，显示触发结果

### 4.10 `/tools/sizing` 仓位建议器

**风险控制模式**：
- 输入 总资金 / 风险偏好% / 入场价 / 止损价 / (可选) 目标价
- 公式：`手数 = 总资金 × 风险% ÷ (入场 - 止损)`，向下取 100 整数手
- 输出：建议手数 / 入场市值 / 最大风险 / 盈亏比

**凯利模式**：
- 输入 总资金 / 入场价 / 胜率 / 平均盈利 / 平均亏损 / 凯利分数（默认 0.25）
- 公式：`f* = (bp - q) / b`，其中 b = avg_win/avg_loss
- 输出：满仓凯利仓位 / 分数凯利仓位 / 投入金额 / 手数
- **可从批量回测的结果直接跳过来**（URL 参数自动预填）

### 4.11 `/tools/backtest` 单只回测

- 输入 代码 / 策略（8 选 1）/ 持有天数 / 回看 K 数
- 结果表：胜率 / 平均收益 / 累计（复利）/ 最佳最差 + 每笔明细
- **资金曲线**：全仓 vs 凯利两条线，最大回撤对比

### 4.12 `/tools/backtest/batch` 批量回测

- 从持仓多选或自填代码（上限 30）+ 同一策略
- 逐只并发跑（6 worker），聚合展示：平均胜率 / 样本加权平均收益 / 正收益标的数
- 每行「→ 凯利」直连仓位建议器（带 URL 参数）

### 4.13 `/tools/optimize` 策略参数网格搜索

- 输入 代码 + 策略族（ma_break / rsi / macd / kdj）+ 回看 K 数
- 遍历参数网格：
  - ma_break：period × hold ∈ [5..60] × [3, 5, 10, 20]（28 组合）
  - rsi：period × hold（20 组合）
  - macd：fast × slow × signal × hold（108 组合）
  - kdj：n × threshold × hold（36 组合）
- 按 `kelly × min(样本/5, 2) + avg_return` 排序，Top 10
- 每行「→ 凯利」直连仓位建议器

---

## 5. CLI 命令一览

| 命令 | 说明 |
|---|---|
| `astock web` | 启 Web UI |
| `astock portfolio` | 打印持仓表（rich 彩色） |
| `astock scan [--top N]` | 全市场扫描 |
| `astock analyze <code>` | 单股 AI 分析 |
| `astock advise` | AI 决策报告 |
| `astock review [-d N]` | AI 复盘最近 N 天 |
| `astock report` | 生成静态 markdown 盘后报告 |
| `astock journal [-c CODE] [-a ACCT] [-d N]` | 查交易历史 |
| `astock buy CODE SHARES PRICE -a ACCT [-n "..."]` | 记买入 |
| `astock sell CODE SHARES PRICE -a ACCT [-n "..."]` | 记卖出 |
| `astock alert list/add/rm` | 关注池 CRUD |
| `astock watch [--interval N] [--notify]` | 一次性或循环预警扫描 |

**示例**：

```bash
astock buy 600519 100 1580.5 -a wp-ky -n "MACD 金叉 + 60日线突破"
astock alert add 002230 -t stop_loss -v 40.0
astock watch --interval 60             # 每 60s 扫一次关注池
astock analyze 000063 | tee /tmp/zte.md
```

---

## 6. 配置文件详解

### 6.1 `config/settings.yaml`

```yaml
scan:
  min_market_cap: 20         # 最低市值（亿元）
  exclude_st: true
  exclude_limit_up: true     # 排除涨停
  max_results: 30

  signals:                   # 技术信号开关（打开的会纳入打分）
    macd_golden_cross: true
    volume_ratio_min: 2.0
    ma_breakthrough: [5, 10, 20, 60]
    rsi_oversold_reversal: true
    kdj_golden_cross: true
    boll_lower_bounce: true
    cci_oversold_reversal: false   # 可选
    dmi_golden_cross: false        # 可选
    sar_bullish_flip: false        # 可选

  composite_scoring: false   # 综合评分：叠加板块资金流（首次运行会拉行业慢一点）

ai:
  model: claude-sonnet-4-6
  max_tokens: 2000

cache:
  spot_ttl_seconds: 60
  hist_ttl_seconds: 86400
  industry_ttl_seconds: 604800

# 后台预警守护（web 启动时按此配置启线程）
alert_daemon:
  enabled: false             # 默认关
  interval_seconds: 300      # 5 分钟一次
  dedup_window_seconds: 3600 # 1 小时内同一 (code, type, ≈price) 只推一次

# 持仓风险监控（跟 alert_daemon 同一循环）
position_monitor:
  enabled: false
  stop_loss_pct: -20         # 亏损 20% 触发
  take_profit_pct: 30        # 盈利 30% 触发
  big_move_pct: 7            # 单日绝对波动 ≥ 7% 触发

# 推送通道
notify:
  serverchan:
    enabled: false
    sendkey: ""              # https://sct.ftqq.com 拿
  mail:
    enabled: false
    smtp_host: smtp.qq.com
    smtp_port: 465
    use_ssl: true
    user: ""                 # 发件人邮箱
    password: ""             # SMTP 授权码（不是登录密码）
    to: ""                   # 收件人
  push_ai_reports:
    advise: false            # AI 决策完成推
    review: false            # AI 复盘完成推
```

### 6.2 `config/holdings.yaml`

买卖后由 `record_trade` 自动改，不建议手动改（除非要清除测试数据）。

### 6.3 `config/watchlist.yaml`

由 `astock alert add/rm` 或 Web `/alerts` 页面改，不建议手动改。

---

## 7. 推送与预警

### 7.1 Server 酱

1. 去 <https://sct.ftqq.com> 用微信扫码登录，拿 sendkey
2. `settings.yaml`:
   ```yaml
   notify:
     serverchan:
       enabled: true
       sendkey: SCTxxxxxxxxxxxxxxxxxx
   ```
3. 测试：让预警触发一次或跑 AI 决策看是否收到

### 7.2 邮件（以 QQ 邮箱为例）

1. QQ 邮箱 → 设置 → 账户 → 开启 SMTP 服务，拿"授权码"
2. `settings.yaml`:
   ```yaml
   notify:
     mail:
       enabled: true
       smtp_host: smtp.qq.com
       smtp_port: 465
       use_ssl: true
       user: youraddr@qq.com
       password: <授权码>
       to: youraddr@qq.com    # 可以是同一地址
   ```

### 7.3 后台预警自动化

`settings.yaml.alert_daemon.enabled: true` 之后，`astock web` 启动时会起一个后台线程：
- 每 `interval_seconds` 秒一次
- 检查关注池所有规则 + 持仓风险（`position_monitor.enabled` 也要打开）
- 触发时通过所有 enabled 的通道推送
- 触发日志写到 `data/alerts.log`

### 7.4 桌面通知（macOS 本地）

CLI 用 `astock watch`（默认开 `--notify`），触发时 `osascript` 弹通知中心。Web daemon 不弹本地弹窗，只走配置的推送通道。

---

## 8. 数据源与缓存

### 数据源

| 数据 | 来源 |
|---|---|
| 实时行情（个股）| 新浪 `hq.sinajs.cn`（gbk） |
| 日线（120 天）| 新浪 `money.finance.sina.com.cn` |
| 全市场列表 | 新浪 `Market_Center.getHQNodeData` 分页；akshare 兜底 |
| 主要指数 | eastmoney `push2delay.eastmoney.com` |
| 行业分类 | eastmoney `push2delay`（7 天缓存） |
| 板块资金流 | eastmoney `push2delay clist` |
| 个股资金流 | eastmoney `push2delay fflow` |
| 个股新闻 | eastmoney `search-api-web` |

所有 HTTP 请求走 `curl_get`（不用 requests），避免系统代理干扰。

### 缓存

`data/cache/` 下按 `md5(key)` 存 JSON：
- spot: 60s
- hist: 1 天
- industry: 7 天
- sector_flow: 5 分钟

清缓存：`rm -rf data/cache`

---

## 9. 常见问题

### Q1: AI 生成一直转圈没响应

- 检查 `.env` 里 `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY` 是否有效
- 检查 `ANTHROPIC_BASE_URL` 是否能访问（用 curl 试试）
- 打开浏览器控制台看 EventSource 是否有 error

### Q2: 扫描或分析报"获取市场数据失败"

- 通常是新浪限流，等 30s 再试
- 或者你机器网络问题，`curl -v https://hq.sinajs.cn/list=sh000001 -H "Referer: https://finance.sina.com.cn"` 看能不能通

### Q3: 行业列全是"未知"

- eastmoney 的 `push2` 主域名从这条线路会 empty-reply，用的是 `push2delay` 镜像
- 如果 delay 也不通，只能等 —— 或者手动改 `data/provider.py::get_industry` 里的 URL

### Q4: 预警不推

- `settings.yaml.alert_daemon.enabled` 是否 true？
- Server 酱 / 邮件配置是否正确？
- 单独测试 notify：进 Python 交互 `from astock.notify import notify; notify("test", "hello")`
- 检查 `data/alerts.log` 里 `notified` 字段

### Q5: 交易表单提交后持仓表没更新

- 提交后 `/trade` 会强制 `load_config()` 并 303 跳转，dashboard 下一次访问应该看到新数据
- 60s 自刷不会重新读 config，只会重新拉行情
- 硬刷新页面（Cmd+R）即可

### Q6: 想改扫描的候选池条件（涨幅、成交额）

在 `screen/scanner.py::scan` 里：

```python
candidates = filtered[
    (filtered["涨跌幅"] >= 1.0) &      # 涨幅下限
    (filtered["涨跌幅"] <= 8.0) &      # 涨幅上限
    (filtered["成交额"] > 1e8)          # 成交额下限
].head(150)                             # 最多分析多少只
```

改后重启 `astock web`。

### Q7: 想用不同的 Claude 模型

`settings.yaml`:

```yaml
ai:
  model: claude-opus-4-6      # 或 claude-haiku-4-5
  max_tokens: 4000
```

### Q8: 卡在扫描中怎么取消

Web `/scan` 页面进行中有「取消」按钮，会在下一轮循环 break，保留已扫到的部分。CLI 只能 Ctrl+C。

### Q9: 想把交易/持仓导出到 Excel 做税务

- 持仓：`/export/portfolio.csv`
- 交易：`/journal` → 「导出 CSV」
- CSV 带 BOM，Excel 双击直接是中文

### Q10: 想跑单元测试

```bash
uv pip install pytest
pytest tests/
```

50 条测试，覆盖 indicators / journal / alerts / sizing / backtest。

---

## 一些个人建议（非功能说明）

- **note 要写**：每笔交易加 `-n "..."` 说清楚为什么买/卖。后面 review 就是从这里挖模式的
- **不要一次开所有信号**：先跑默认（MA/MACD/RSI/KDJ/BOLL/量比）看结果质量，再逐步开 CCI/DMI/SAR
- **回测样本 < 10 别当真**：`/tools/optimize` 会剔 < 3 但你自己判断时要 ≥ 10 才算有统计意义
- **凯利分数默认 0.25 别贪**：全凯利波动巨大心态崩，散户 0.25 分数凯利已经很激进
- **AI 决策别照抄**：Claude 不知道你不知道的东西（心态、税务、家庭现金流）。它给方向，你做决定
