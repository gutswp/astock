"""仓位建议器：基于止损位的风险控制."""
from dataclasses import dataclass


@dataclass
class SizingInput:
    capital: float          # 总资金（元）
    risk_pct: float         # 单笔可承受损失占总资金比例（如 2 表示 2%）
    entry_price: float
    stop_price: float
    target_price: float | None = None


@dataclass
class SizingResult:
    max_risk_amount: float      # 允许的最大亏损金额
    loss_per_share: float       # 单股潜在亏损
    raw_shares: int             # 按公式算出的手数（未取整到 100）
    shares: int                 # 建议手数（A股 100 整数手）
    position_value: float       # 入场市值
    position_pct: float         # 入场占总资金 %
    risk_reward: float | None   # 盈亏比（有 target 时）
    warning: str | None = None  # 校验错误


def compute(inp: SizingInput) -> SizingResult:
    if inp.entry_price <= 0 or inp.capital <= 0:
        return SizingResult(0, 0, 0, 0, 0, 0, None, "参数无效")
    if inp.stop_price >= inp.entry_price:
        return SizingResult(0, 0, 0, 0, 0, 0, None, "止损价必须低于入场价")

    max_risk = inp.capital * (inp.risk_pct / 100)
    loss_per = inp.entry_price - inp.stop_price
    raw = max_risk / loss_per
    shares = (int(raw) // 100) * 100  # A 股 100 股整数手
    position_value = shares * inp.entry_price
    position_pct = position_value / inp.capital * 100

    rr = None
    if inp.target_price and inp.target_price > inp.entry_price:
        rr = (inp.target_price - inp.entry_price) / loss_per

    warning = None
    if shares == 0:
        warning = "按此风险/止损，最大仓位不足 100 股。可调宽止损或提高风险偏好。"
    elif position_pct > 30:
        warning = "单标的仓位超 30%，集中度偏高，建议分批入场或降低风险偏好。"

    return SizingResult(
        max_risk_amount=round(max_risk, 2),
        loss_per_share=round(loss_per, 3),
        raw_shares=int(raw),
        shares=shares,
        position_value=round(position_value, 2),
        position_pct=round(position_pct, 2),
        risk_reward=round(rr, 2) if rr is not None else None,
        warning=warning,
    )
