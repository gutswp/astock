from rich.console import Console
from rich.table import Table

from astock.portfolio.models import PortfolioSummary


def _fmt_money(val: float) -> str:
    if abs(val) >= 10000:
        return f"{val/10000:.2f}万"
    return f"{val:.2f}"


def _fmt_pct(val: float) -> str:
    return f"{val:+.2f}%"


def _color_val(val: float, fmt_fn=None) -> str:
    s = fmt_fn(val) if fmt_fn else f"{val:.2f}"
    if val > 0:
        return f"[red]{s}[/red]"
    elif val < 0:
        return f"[green]{s}[/green]"
    return s


def print_portfolio(summary: PortfolioSummary) -> None:
    console = Console(width=130)

    console.print()
    console.print("[bold]== 持仓汇总（跨账户合并） ==[/bold]")
    console.print(
        f"  总市值: [bold]{_fmt_money(summary.total_market_value)}[/bold]"
        f"  |  总成本: {_fmt_money(summary.total_cost)}"
        f"  |  浮动盈亏: {_color_val(summary.total_profit, _fmt_money)}"
        f" ({_color_val(summary.total_profit_pct, _fmt_pct)})"
    )
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, pad_edge=False, expand=True)
    table.add_column("股票", style="bold", ratio=3)
    table.add_column("代码", ratio=2)
    table.add_column("现价", justify="right", ratio=2)
    table.add_column("持股", justify="right", ratio=2)
    table.add_column("市值", justify="right", ratio=2)
    table.add_column("占比", justify="right", ratio=1)
    table.add_column("成本", justify="right", ratio=2)
    table.add_column("盈亏", justify="right", ratio=2)
    table.add_column("盈亏%", justify="right", ratio=2)
    table.add_column("今日", justify="right", ratio=2)
    table.add_column("账户", ratio=3)

    for p in summary.positions:
        pct_of_total = p.market_value / summary.total_market_value * 100 if summary.total_market_value else 0
        table.add_row(
            p.name,
            p.code,
            f"{p.current_price:.2f}",
            str(p.total_shares),
            _fmt_money(p.market_value),
            f"{pct_of_total:.1f}%",
            f"{p.avg_cost:.2f}",
            _color_val(p.profit, _fmt_money),
            _color_val(p.profit_pct, _fmt_pct),
            _color_val(p.daily_change, _fmt_pct),
            " ".join(p.accounts),
        )

    console.print(table)

    industry_map: dict[str, float] = {}
    for p in summary.positions:
        ind = p.industry or "未知"
        industry_map[ind] = industry_map.get(ind, 0) + p.market_value
    if any(i != "未知" for i in industry_map):
        console.print()
        console.print("[bold]行业分布[/bold]")
        for ind, val in sorted(industry_map.items(), key=lambda x: -x[1]):
            pct = val / summary.total_market_value * 100 if summary.total_market_value else 0
            bar = "█" * int(pct / 2)
            console.print(f"  {ind:<8} {_fmt_money(val):>8}  {pct:5.1f}%  {bar}")

    console.print()


def print_scan_results(results: list[dict]) -> None:
    console = Console(width=130)
    if not results:
        console.print("[yellow]未发现符合条件的机会[/yellow]")
        return

    console.print()
    console.print(f"[bold]== 机会扫描结果 ({len(results)} 只) ==[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, expand=True)
    table.add_column("股票", style="bold", ratio=3)
    table.add_column("代码", ratio=2)
    table.add_column("现价", justify="right", ratio=2)
    table.add_column("涨跌%", justify="right", ratio=2)
    table.add_column("量比", justify="right", ratio=1)
    table.add_column("信号", ratio=6)
    table.add_column("得分", justify="right", ratio=1)

    for r in results:
        table.add_row(
            r.get("name", ""),
            r.get("code", ""),
            f"{r.get('price', 0):.2f}",
            _color_val(r.get("change_pct", 0), _fmt_pct),
            f"{r.get('volume_ratio', 0):.1f}",
            " | ".join(r.get("signals", [])),
            f"[bold]{r.get('score', 0)}[/bold]",
        )

    console.print(table)
    console.print()
