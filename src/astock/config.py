from dataclasses import dataclass, field
from pathlib import Path

import yaml

from astock import CONFIG_DIR


@dataclass
class HoldingConfig:
    code: str
    name: str
    shares: int
    cost: float


@dataclass
class AccountConfig:
    name: str
    broker: str
    holdings: list[HoldingConfig] = field(default_factory=list)


@dataclass
class ScanConfig:
    min_market_cap: float = 20
    exclude_st: bool = True
    exclude_limit_up: bool = True
    max_results: int = 30
    volume_ratio_min: float = 2.0
    ma_breakthrough: list[int] = field(default_factory=lambda: [5, 10, 20, 60])
    fund_flow_min: float = 5000
    macd_golden_cross: bool = True


@dataclass
class AppConfig:
    accounts: list[AccountConfig]
    scan: ScanConfig
    ai_model: str = "claude-sonnet-4-6"
    ai_max_tokens: int = 2000


def load_holdings(path: Path | None = None) -> list[AccountConfig]:
    path = path or CONFIG_DIR / "holdings.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    accounts = []
    for acct in raw["accounts"]:
        holdings = [HoldingConfig(**h) for h in acct["holdings"]]
        accounts.append(AccountConfig(name=acct["name"], broker=acct["broker"], holdings=holdings))
    return accounts


def load_settings(path: Path | None = None) -> ScanConfig:
    path = path or CONFIG_DIR / "settings.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    s = raw.get("scan", {})
    signals = s.get("signals", {})
    return ScanConfig(
        min_market_cap=s.get("min_market_cap", 20),
        exclude_st=s.get("exclude_st", True),
        exclude_limit_up=s.get("exclude_limit_up", True),
        max_results=s.get("max_results", 30),
        volume_ratio_min=signals.get("volume_ratio_min", 2.0),
        ma_breakthrough=signals.get("ma_breakthrough", [5, 10, 20, 60]),
        fund_flow_min=signals.get("fund_flow_min", 5000),
        macd_golden_cross=signals.get("macd_golden_cross", True),
    )


def load_config() -> AppConfig:
    accounts = load_holdings()
    scan = load_settings()
    settings_path = CONFIG_DIR / "settings.yaml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    ai = raw.get("ai", {})
    return AppConfig(
        accounts=accounts,
        scan=scan,
        ai_model=ai.get("model", "claude-sonnet-4-6"),
        ai_max_tokens=ai.get("max_tokens", 2000),
    )
