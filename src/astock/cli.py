import click

from astock.config import load_config


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AStock - AI Agent for Chinese A-Share Investors"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@cli.command()
@click.pass_context
def portfolio(ctx: click.Context) -> None:
    """Show merged portfolio across all accounts."""
    from astock.portfolio.manager import show_portfolio

    show_portfolio(ctx.obj["config"])


@cli.command()
@click.option("--top", default=30, help="Max results to show.")
@click.pass_context
def scan(ctx: click.Context, top: int) -> None:
    """Scan market for opportunities (run after market close)."""
    from astock.screen.scanner import run_scan

    config = ctx.obj["config"]
    config.scan.max_results = top
    run_scan(config)


@cli.command()
@click.argument("code")
@click.pass_context
def analyze(ctx: click.Context, code: str) -> None:
    """Analyze a stock with AI (holding or candidate)."""
    from astock.ai.analyst import analyze_stock

    analyze_stock(code, ctx.obj["config"])


@cli.command()
@click.pass_context
def report(ctx: click.Context) -> None:
    """Generate daily post-market report (portfolio + opportunities)."""
    from astock.render.report import generate_report

    generate_report(ctx.obj["config"])


@cli.command()
@click.pass_context
def advise(ctx: click.Context) -> None:
    """AI 决策报告：给出今日持仓/加仓/减仓操作清单。"""
    from astock.ai.advisor import run_advise

    run_advise(ctx.obj["config"])


@cli.command()
@click.argument("code")
@click.argument("shares", type=int)
@click.argument("price", type=float)
@click.option("--account", "-a", required=True, help="Account name (e.g., wp-ky)")
@click.option("--note", "-n", default=None, help="买入理由（会记入日志）")
def buy(code: str, shares: int, price: float, account: str, note: str | None) -> None:
    """Record a buy trade."""
    from astock.portfolio.manager import record_trade

    record_trade(account, code, shares, price, "buy", note=note)


@cli.command()
@click.argument("code")
@click.argument("shares", type=int)
@click.argument("price", type=float)
@click.option("--account", "-a", required=True, help="Account name (e.g., wp-ky)")
@click.option("--note", "-n", default=None, help="卖出理由（会记入日志）")
def sell(code: str, shares: int, price: float, account: str, note: str | None) -> None:
    """Record a sell trade."""
    from astock.portfolio.manager import record_trade

    record_trade(account, code, shares, price, "sell", note=note)


@cli.command()
@click.option("--code", "-c", default=None, help="按代码过滤")
@click.option("--account", "-a", default=None, help="按账户过滤")
@click.option("--days", "-d", default=None, type=int, help="只看最近 N 天")
def journal(code: str | None, account: str | None, days: int | None) -> None:
    """查看交易历史（含 note）。"""
    from astock.render.tables import print_journal
    from astock.portfolio.journal import load_trades

    trades = load_trades(code=code, account=account, days=days)
    print_journal(trades)


@cli.command()
@click.option("--days", "-d", default=90, type=int, help="回看 N 天（默认 90）")
@click.pass_context
def review(ctx: click.Context, days: int) -> None:
    """AI 复盘：从交易日志提取模式与归因。"""
    from astock.ai.reviewer import run_review

    run_review(ctx.obj["config"], days=days)


@cli.group()
def alert() -> None:
    """管理关注池预警规则（config/watchlist.yaml）。"""


@alert.command("list")
def alert_list() -> None:
    """查看当前关注池。"""
    from astock.render.tables import print_watchlist
    from astock.screen.alerts import load_watchlist

    print_watchlist(load_watchlist())


@alert.command("add")
@click.argument("code")
@click.option("--type", "-t", "alert_type", required=True,
              help="price_above/price_below/stop_loss/change_above/change_below/ma_break/macd_cross")
@click.option("--value", "-v", default=None, type=float, help="阈值（macd_cross 不需要）")
@click.option("--period", "-p", default=None, type=int, help="ma_break 的均线周期")
def alert_add(code: str, alert_type: str, value: float | None, period: int | None) -> None:
    """添加一条预警规则。"""
    from rich.console import Console
    from astock.screen.alerts import add_watch_alert

    try:
        w = add_watch_alert(code, alert_type, value, period)
    except ValueError as e:
        Console().print(f"[red]{e}[/red]")
        return
    Console().print(f"[green]已添加 {w.code} {w.name} 的 {alert_type} 规则[/green]")


@alert.command("rm")
@click.argument("code")
@click.option("--index", "-i", default=None, type=int, help="删除该 code 下第 N 条（不给则整只清出）")
def alert_rm(code: str, index: int | None) -> None:
    """移除关注股或某条规则。"""
    from rich.console import Console
    from astock.screen.alerts import remove_watch

    try:
        remove_watch(code, index)
    except ValueError as e:
        Console().print(f"[red]{e}[/red]")
        return
    Console().print(f"[green]已移除 {code}{f' 的规则 #{index}' if index is not None else ''}[/green]")


@cli.command()
@click.option("--interval", "-i", default=None, type=int, help="轮询间隔秒数；不给则单次运行")
@click.option("--notify/--no-notify", default=True, help="触发时是否发 macOS 桌面通知")
def watch(interval: int | None, notify: bool) -> None:
    """扫描关注池，触发时打印/通知。cron 场景用 --interval 不指定即可。"""
    from astock.screen.watcher import run_watch

    run_watch(interval=interval, notify=notify)


if __name__ == "__main__":
    cli()
