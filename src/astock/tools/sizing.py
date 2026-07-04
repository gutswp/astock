"""仓位建议器：基于止损位的风险控制 + 凯利公式两种模式."""
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


# --- 凯利模式 -----------------------------------------------------------------

@dataclass
class KellyInput:
    capital: float          # 总资金
    entry_price: float
    win_rate: float         # % (0~100)
    avg_win: float          # % 平均单笔盈利（正数）
    avg_loss: float         # % 平均单笔亏损（正数）
    fraction: float = 0.25  # 分数凯利，避免用满


@dataclass
class KellyResult:
    full_kelly_pct: float       # 满仓凯利占资金 %
    fraction_used: float        # 采用的凯利分数
    kelly_pct: float            # 分数凯利后的建议仓位 %
    kelly_amount: float         # 建议投入金额
    shares: int                 # 建议手数（100 整数）
    warning: str | None = None


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """标准凯利公式 f* = (bp - q) / b，返回小数（0~1，可能为负）."""
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    p = win_rate / 100
    q = 1 - p
    b = avg_win / avg_loss
    return (b * p - q) / b


def compute_kelly(inp: KellyInput) -> KellyResult:
    if inp.capital <= 0 or inp.entry_price <= 0:
        return KellyResult(0, inp.fraction, 0, 0, 0, "参数无效")

    f = kelly_fraction(inp.win_rate, inp.avg_win, inp.avg_loss)
    warning: str | None = None
    if f <= 0:
        warning = "凯利公式返回 ≤0：期望值为负，不建议做这个策略。"
        return KellyResult(round(f * 100, 2), inp.fraction, 0, 0, 0, warning)

    fraction = max(0.05, min(inp.fraction, 1.0))  # 限制在 5%~100%
    kelly_pct = f * fraction
    if kelly_pct > 0.5:
        warning = "分数凯利后仍超 50% 资金，风险偏大。可考虑更小分数（如 0.1）。"
    amount = inp.capital * kelly_pct
    raw_shares = amount / inp.entry_price
    shares = (int(raw_shares) // 100) * 100
    if shares == 0:
        warning = warning or "按此仓位不足 100 股，可加大分数或增加资金。"

    return KellyResult(
        full_kelly_pct=round(f * 100, 2),
        fraction_used=fraction,
        kelly_pct=round(kelly_pct * 100, 2),
        kelly_amount=round(amount, 2),
        shares=shares,
        warning=warning,
    )
