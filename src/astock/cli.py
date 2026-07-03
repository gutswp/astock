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
@click.argument("code")
@click.argument("shares", type=int)
@click.argument("price", type=float)
@click.option("--account", "-a", required=True, help="Account name (e.g., wp-ky)")
def buy(code: str, shares: int, price: float, account: str) -> None:
    """Record a buy trade."""
    from astock.portfolio.manager import record_trade

    record_trade(account, code, shares, price, "buy")


@cli.command()
@click.argument("code")
@click.argument("shares", type=int)
@click.argument("price", type=float)
@click.option("--account", "-a", required=True, help="Account name (e.g., wp-ky)")
def sell(code: str, shares: int, price: float, account: str) -> None:
    """Record a sell trade."""
    from astock.portfolio.manager import record_trade

    record_trade(account, code, shares, price, "sell")


if __name__ == "__main__":
    cli()
