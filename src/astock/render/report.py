from datetime import datetime
from pathlib import Path

from rich.console import Console

from astock import DATA_DIR
from astock.config import AppConfig
from astock.portfolio.manager import build_portfolio


def generate_report(config: AppConfig) -> None:
    console = Console()
    console.print("[dim]正在生成盘后报告...[/dim]")

    summary = build_portfolio(config)
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# AStock 盘后报告 {today}",
        "",
        "## 持仓汇总",
        "",
        f"- 总市值: {summary.total_market_value/10000:.2f}万",
        f"- 总成本: {summary.total_cost/10000:.2f}万",
        f"- 浮动盈亏: {summary.total_profit/10000:.2f}万 ({summary.total_profit_pct:+.2f}%)",
        "",
        "## 持仓明细",
        "",
        "| 股票 | 代码 | 现价 | 持股 | 市值 | 盈亏% | 今日 | 账户 |",
        "|------|------|------|------|------|-------|------|------|",
    ]

    for p in summary.positions:
        lines.append(
            f"| {p.name} | {p.code} | {p.current_price:.2f} | {p.total_shares} | "
            f"{p.market_value/10000:.2f}万 | {p.profit_pct:+.2f}% | {p.daily_change:+.2f}% | "
            f"{' '.join(p.accounts)} |"
        )

    # 按今日涨跌排序
    sorted_by_daily = sorted(summary.positions, key=lambda p: p.daily_change, reverse=True)

    lines.extend([
        "",
        "## 今日表现",
        "",
        "**涨幅前三:**",
    ])
    for p in sorted_by_daily[:3]:
        lines.append(f"- {p.name} {p.daily_change:+.2f}%")

    lines.append("")
    lines.append("**跌幅前三:**")
    for p in sorted_by_daily[-3:]:
        lines.append(f"- {p.name} {p.daily_change:+.2f}%")

    # 风险提示
    deep_loss = [p for p in summary.positions if p.profit_pct < -20]
    if deep_loss:
        lines.extend([
            "",
            "## 风险提示",
            "",
            "以下持仓亏损超过20%，建议关注:",
        ])
        for p in deep_loss:
            lines.append(f"- **{p.name}** ({p.code}): 亏损 {p.profit_pct:.2f}%，成本 {p.avg_cost:.2f}，现价 {p.current_price:.2f}")

    lines.append("")

    # 写文件
    report_dir = DATA_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    console.print(f"[green]报告已生成: {report_path}[/green]")

    # 同时在终端输出
    from rich.markdown import Markdown
    console.print()
    console.print(Markdown("\n".join(lines)))
