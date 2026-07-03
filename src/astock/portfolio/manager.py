from collections import defaultdict
from pathlib import Path

import yaml

from astock import CONFIG_DIR
from astock.config import AppConfig, load_holdings
from astock.data.provider import get_spot
from astock.portfolio.models import Holding, Position, PortfolioSummary
from astock.render.tables import print_portfolio


def _collect_holdings(config: AppConfig) -> list[Holding]:
    holdings = []
    for acct in config.accounts:
        for h in acct.holdings:
            holdings.append(Holding(
                code=h.code, name=h.name, shares=h.shares,
                cost=h.cost, account=acct.name, broker=acct.broker,
            ))
    return holdings


def _merge_positions(holdings: list[Holding], spot_df) -> list[Position]:
    grouped: dict[str, list[Holding]] = defaultdict(list)
    for h in holdings:
        grouped[h.code].append(h)

    price_map = {}
    change_map = {}
    if not spot_df.empty:
        for _, row in spot_df.iterrows():
            price_map[row["代码"]] = row["最新价"]
            change_map[row["代码"]] = row.get("涨跌幅", 0)

    positions = []
    for code, group in grouped.items():
        total_shares = sum(h.shares for h in group)
        total_cost_value = sum(h.shares * h.cost for h in group)
        avg_cost = total_cost_value / total_shares if total_shares else 0
        current_price = price_map.get(code, 0)
        market_value = current_price * total_shares
        profit = market_value - total_cost_value
        profit_pct = (profit / total_cost_value * 100) if total_cost_value else 0
        daily_change = change_map.get(code, 0)
        accounts = sorted(set(h.account for h in group))

        positions.append(Position(
            code=code, name=group[0].name,
            total_shares=total_shares, avg_cost=round(avg_cost, 3),
            current_price=current_price, market_value=round(market_value, 2),
            profit=round(profit, 2), profit_pct=round(profit_pct, 2),
            daily_change=round(daily_change, 2),
            industry="",
            accounts=accounts,
        ))

    positions.sort(key=lambda p: p.market_value, reverse=True)
    return positions


def build_portfolio(config: AppConfig) -> PortfolioSummary:
    holdings = _collect_holdings(config)
    codes = list(set(h.code for h in holdings))
    spot_df = get_spot(codes)

    positions = _merge_positions(holdings, spot_df)

    total_market_value = sum(p.market_value for p in positions)
    total_cost = sum(p.total_shares * p.avg_cost for p in positions)
    total_profit = total_market_value - total_cost

    return PortfolioSummary(
        total_assets=total_market_value,
        total_market_value=total_market_value,
        total_cost=total_cost,
        total_profit=round(total_profit, 2),
        total_profit_pct=round(total_profit / total_cost * 100, 2) if total_cost else 0,
        cash=0,
        position_ratio=100.0,
        positions=positions,
    )


def show_portfolio(config: AppConfig) -> None:
    summary = build_portfolio(config)
    print_portfolio(summary)


def record_trade(account: str, code: str, shares: int, price: float, action: str) -> None:
    path = CONFIG_DIR / "holdings.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    target_acct = None
    for acct in raw["accounts"]:
        if acct["name"] == account:
            target_acct = acct
            break

    if target_acct is None:
        from rich.console import Console
        Console().print(f"[red]账户 {account} 不存在[/red]")
        return

    existing = None
    for h in target_acct["holdings"]:
        if h["code"] == code:
            existing = h
            break

    if action == "buy":
        if existing:
            old_total = existing["shares"] * existing["cost"]
            new_total = shares * price
            existing["shares"] += shares
            existing["cost"] = round((old_total + new_total) / existing["shares"], 3)
        else:
            target_acct["holdings"].append({
                "code": code, "name": code, "shares": shares, "cost": price,
            })
    elif action == "sell":
        if existing:
            existing["shares"] -= shares
            if existing["shares"] <= 0:
                target_acct["holdings"].remove(existing)
        else:
            from rich.console import Console
            Console().print(f"[red]账户 {account} 中没有 {code}[/red]")
            return

    path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    from rich.console import Console
    Console().print(f"[green]{action.upper()} {code} x{shares} @{price} 已更新到 {account}[/green]")
