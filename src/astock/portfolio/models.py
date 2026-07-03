from dataclasses import dataclass


@dataclass
class Holding:
    code: str
    name: str
    shares: int
    cost: float
    account: str
    broker: str


@dataclass
class Position:
    code: str
    name: str
    total_shares: int
    avg_cost: float
    current_price: float
    market_value: float
    profit: float
    profit_pct: float
    daily_change: float
    industry: str
    accounts: list[str]


@dataclass
class PortfolioSummary:
    total_assets: float
    total_market_value: float
    total_cost: float
    total_profit: float
    total_profit_pct: float
    cash: float
    position_ratio: float
    positions: list[Position]
