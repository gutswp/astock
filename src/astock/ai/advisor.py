from datetime import datetime

import anthropic
from rich.console import Console
from rich.markdown import Markdown

from astock import DATA_DIR
from astock.ai.client import make_client
from astock.config import AppConfig
from astock.data.provider import get_indices, get_sector_flow
from astock.portfolio.manager import build_portfolio
from astock.portfolio.models import PortfolioSummary
from astock.screen.scanner import scan

SYSTEM_PROMPT = """你是一位专业的 A 股组合管理顾问。用户会给你他当前的持仓、大盘/板块状态、以及扫描出的机会池，你需要给出**今日决策清单**——直接、可执行、有优先级。

输出结构（用 Markdown，严格按顺序）：

## 1. 市场态势
一段话概括：大盘方向、板块热度、整体环境适合进攻/防守/观望。

## 2. 持仓操作清单
按优先级排序，每条一行，格式：
- **代码 名称**：动作（**清仓/减半/减1/3/持有/加仓**）— 具体理由（结合成本、当前价、技术面、行业）

清仓/减仓建议要优先——用户主要痛点是账户浮亏 15%+。**不要**对每只都给建议，只对**需要动的**给。

## 3. 候选池 Top 3
从机会池里挑最匹配当下环境的 3 只，格式：
- **代码 名称**（信号：xxx）— 为什么值得关注、建议仓位（重仓/试仓/观察）

**注意**：如果整体行情弱、账户已亏损，明确说"暂不建议加新仓，先处理存量"。

## 4. 风险与提醒
- 集中度风险（哪个行业过重）
- 深度亏损标的的止损底线
- 大盘系统性风险信号

要求：
- 用中文，简洁直接，不要空泛套话
- 每个建议都要能落地（写清价格/仓位/时机）
- 用户主要账户浮亏，情绪敏感——给建议时要客观但不冷冰冰
"""


def _fmt_positions(summary: PortfolioSummary) -> str:
    lines = ["| 代码 | 名称 | 行业 | 持股 | 成本 | 现价 | 盈亏% | 今日% | 市值占比 |",
             "|---|---|---|---|---|---|---|---|---|"]
    total = summary.total_market_value or 1
    for p in summary.positions:
        lines.append(
            f"| {p.code} | {p.name} | {p.industry} | {p.total_shares} | "
            f"{p.avg_cost:.2f} | {p.current_price:.2f} | "
            f"{p.profit_pct:+.2f}% | {p.daily_change:+.2f}% | "
            f"{p.market_value / total * 100:.1f}% |"
        )
    return "\n".join(lines)


def _fmt_indices(df) -> str:
    if df.empty:
        return "（大盘数据获取失败）"
    lines = []
    for _, r in df.iterrows():
        lines.append(f"- {r['名称']} {r['最新价']:.2f} ({r['涨跌幅']:+.2f}%)")
    return "\n".join(lines)


def _fmt_sectors(df) -> str:
    if df.empty:
        return "（板块资金流数据不可用）"
    top = df.head(8)
    lines = []
    for _, r in top.iterrows():
        name = r.get("名称") or r.get("行业") or ""
        change = r.get("今日涨跌幅") or r.get("涨跌幅") or 0
        inflow = r.get("今日主力净流入-净额") or r.get("主力净流入-净额") or 0
        try:
            inflow_yi = float(inflow) / 1e8
        except Exception:
            inflow_yi = 0
        lines.append(f"- {name}  涨跌 {float(change):+.2f}%  主力净流入 {inflow_yi:+.2f}亿")
    return "\n".join(lines)


def _fmt_opportunities(results: list[dict], limit: int = 15) -> str:
    if not results:
        return "（扫描无结果）"
    top = results[:limit]
    lines = ["| 代码 | 名称 | 现价 | 涨跌% | 量比 | 信号 | 得分 |",
             "|---|---|---|---|---|---|---|"]
    for r in top:
        lines.append(
            f"| {r['code']} | {r['name']} | {r['price']:.2f} | "
            f"{r['change_pct']:+.2f}% | {r['volume_ratio']:.1f} | "
            f"{' / '.join(r['signals'])} | {r['score']} |"
        )
    return "\n".join(lines)


def _build_context(config: AppConfig, console: Console) -> str:
    console.print("[dim]· 拉取持仓...[/dim]")
    summary = build_portfolio(config)

    console.print("[dim]· 拉取大盘指数...[/dim]")
    indices = get_indices()

    console.print("[dim]· 拉取板块资金流...[/dim]")
    sectors = get_sector_flow()

    console.print("[dim]· 全市场扫描...[/dim]")
    opportunities = scan(config, silent=True)

    parts = [
        f"# 决策上下文（{datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        "",
        "## 大盘指数",
        _fmt_indices(indices),
        "",
        "## 板块资金流 Top",
        _fmt_sectors(sectors),
        "",
        f"## 我的持仓（总市值 {summary.total_market_value/10000:.2f}万，浮盈亏 {summary.total_profit/10000:+.2f}万 / {summary.total_profit_pct:+.2f}%）",
        _fmt_positions(summary),
        "",
        "## 机会池（扫描 Top）",
        _fmt_opportunities(opportunities),
    ]
    return "\n".join(parts)


def _save_advise(advice: str, context: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    reports_dir = DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{today}.advise.md"
    out_path.write_text(
        f"# AStock AI 决策报告 {today}\n\n{advice}\n\n---\n\n<details><summary>决策上下文</summary>\n\n{context}\n\n</details>\n",
        encoding="utf-8",
    )
    return str(out_path)


def generate_advise(config: AppConfig, console: Console | None = None) -> tuple[str, str]:
    """执行决策报告生成，返回 (advice_markdown, saved_path_str)."""
    console = console or Console(quiet=True)
    context = _build_context(config, console)

    client = make_client()
    response = client.messages.create(
        model=config.ai_model,
        max_tokens=max(config.ai_max_tokens, 4000),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    advice = response.content[0].text
    path = _save_advise(advice, context)
    return advice, path


def stream_advise(config: AppConfig):
    """流式生成决策：yield (event_type, data)。event_type ∈ {stage, chunk, done, error}."""
    try:
        yield ("stage", "拉取持仓 / 大盘 / 板块 / 机会池")
        context = _build_context(config, Console(quiet=True))
        yield ("stage", "调用 AI 生成决策")

        client = make_client()
        buf = []
        with client.messages.stream(
            model=config.ai_model,
            max_tokens=max(config.ai_max_tokens, 4000),
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        ) as stream:
            for text in stream.text_stream:
                buf.append(text)
                yield ("chunk", text)

        advice = "".join(buf)
        path = _save_advise(advice, context)
        # 可选推送
        try:
            from astock.notify import notify, should_push_ai
            if should_push_ai("advise"):
                notify(f"🤖 AStock 决策报告 {datetime.now():%m-%d}", advice)
        except Exception:
            pass
        yield ("done", path)
    except Exception as e:
        yield ("error", str(e))


def run_advise(config: AppConfig) -> None:
    console = Console(width=110)
    console.print("[bold]== 生成 AI 决策报告 ==[/bold]")
    try:
        advice, path = generate_advise(config, console=console)
    except anthropic.AuthenticationError:
        console.print("[red]API Key 无效或未设置[/red]")
        return
    console.print("[dim]· 调用 AI 生成决策...完成[/dim]")
    console.print()
    console.print(Markdown(advice))
    console.print()
    console.print(f"[green]报告已保存: {path}[/green]")
