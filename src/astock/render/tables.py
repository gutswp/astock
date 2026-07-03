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


def print_watchlist(watches: list) -> None:
    console = Console(width=120)
    if not watches:
        console.print("[yellow]关注池为空。用 astock alert add <code> -t <type> -v <val> 添加规则。[/yellow]")
        return
    console.print()
    console.print(f"[bold]== 关注池 ({len(watches)} 只) ==[/bold]")
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("代码", ratio=2)
    table.add_column("名称", ratio=3)
    table.add_column("#", justify="right", ratio=1)
    table.add_column("规则", ratio=8)
    for w in watches:
        rules = []
        for i, a in enumerate(w.alerts):
            desc = a.type
            if a.value is not None:
                desc += f"={a.value}"
            if a.period is not None:
                desc += f",period={a.period}"
            rules.append(f"[dim]#{i}[/dim] {desc}")
        table.add_row(w.code, w.name, str(len(w.alerts)), " | ".join(rules) or "-")
    console.print(table)
    console.print()


def print_triggered_alerts(triggered: list[dict]) -> None:
    console = Console(width=120)
    if not triggered:
        console.print("[dim]无预警触发[/dim]")
        return
    console.print()
    console.print(f"[bold red]!! 触发 {len(triggered)} 条预警 !![/bold red]")
    table = Table(show_header=True, header_style="bold red", expand=True)
    table.add_column("代码", ratio=2)
    table.add_column("名称", ratio=3)
    table.add_column("类型", ratio=3)
    table.add_column("现价", justify="right", ratio=2)
    table.add_column("涨跌%", justify="right", ratio=2)
    table.add_column("信息", ratio=6)
    for t in triggered:
        table.add_row(
            t["code"], t["name"], t["type"],
            f"{t['price']:.2f}",
            _color_val(t["change_pct"], _fmt_pct),
            t["message"],
        )
    console.print(table)
    console.print()


def print_journal(trades: list[dict]) -> None:
    console = Console(width=130)
    if not trades:
        console.print("[yellow]没有匹配的交易记录[/yellow]")
        return

    console.print()
    console.print(f"[bold]== 交易日志 ({len(trades)} 条) ==[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold", show_lines=False, expand=True)
    table.add_column("时间", ratio=3)
    table.add_column("账户", ratio=2)
    table.add_column("方向", ratio=1)
    table.add_column("代码", ratio=2)
    table.add_column("名称", ratio=3)
    table.add_column("量", justify="right", ratio=2)
    table.add_column("价", justify="right", ratio=2)
    table.add_column("备注", ratio=5)

    for t in trades:
        action = t.get("action", "")
        color = "red" if action == "buy" else "green"
        table.add_row(
            t.get("ts", "")[:16],
            t.get("account", ""),
            f"[{color}]{action.upper()}[/{color}]",
            t.get("code", ""),
            t.get("name", ""),
            str(t.get("shares", "")),
            f"{t.get('price', 0):.2f}",
            t.get("note") or "",
        )
    console.print(table)
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
