from astock.tools.sizing import (
    KellyInput,
    SizingInput,
    compute,
    compute_kelly,
    kelly_fraction,
)


def test_basic_case():
    r = compute(SizingInput(capital=100000, risk_pct=2, entry_price=10, stop_price=9))
    # 风险金额 = 2000，单股亏 1 → 2000 股，取整 100 手 → 2000
    assert r.shares == 2000
    assert r.max_risk_amount == 2000
    assert r.position_value == 20000
    assert r.warning is None


def test_shares_rounds_down_to_100():
    r = compute(SizingInput(capital=100000, risk_pct=2, entry_price=10, stop_price=9.7))
    # 单股亏 0.3 → 6666.67 股 → 取整 6600
    assert r.shares == 6600


def test_stop_above_entry_error():
    r = compute(SizingInput(capital=100000, risk_pct=2, entry_price=10, stop_price=11))
    assert r.shares == 0
    assert "止损" in r.warning


def test_shares_zero_warning():
    r = compute(SizingInput(capital=1000, risk_pct=0.1, entry_price=100, stop_price=99))
    # 风险 1 元 / 单股亏 1 → 1 股 → 取整 0
    assert r.shares == 0
    assert r.warning is not None


def test_risk_reward_computed():
    r = compute(SizingInput(capital=100000, risk_pct=2, entry_price=10,
                            stop_price=9, target_price=13))
    # (13-10)/(10-9) = 3
    assert r.risk_reward == 3.0


def test_concentration_warning():
    r = compute(SizingInput(capital=10000, risk_pct=5, entry_price=1, stop_price=0.9))
    # 风险 500，单股亏 0.1 → 5000 股 → 5000 元 → 占比 50%
    assert r.position_pct > 30
    assert r.warning is not None


# --- Kelly ------------------------------------------------------------------

def test_kelly_fair_coin_1_1_ratio():
    # 胜率 50% 且 1:1 盈亏比 → f* = 0
    assert kelly_fraction(50, 1, 1) == 0


def test_kelly_positive_edge():
    # 胜率 60% 且 1:1 → (1*0.6 - 0.4)/1 = 0.2
    assert abs(kelly_fraction(60, 1, 1) - 0.2) < 1e-6


def test_kelly_2_to_1():
    # 胜率 50%，盈亏比 2:1 → (2*0.5 - 0.5)/2 = 0.25
    assert abs(kelly_fraction(50, 2, 1) - 0.25) < 1e-6


def test_kelly_negative_edge():
    # 胜率 30% 且 1:1 → 负值
    assert kelly_fraction(30, 1, 1) < 0


def test_compute_kelly_shares():
    r = compute_kelly(KellyInput(
        capital=100000, entry_price=10,
        win_rate=60, avg_win=5, avg_loss=3,
        fraction=0.25,
    ))
    # full = (5/3 * 0.6 - 0.4)/(5/3) = (1.0 - 0.4)/1.667 ≈ 0.36
    # kelly = 0.36 × 0.25 ≈ 0.09 → 9000 元 → 900 股 → 900
    assert r.full_kelly_pct > 30
    assert r.shares > 0
    assert r.shares % 100 == 0


def test_compute_kelly_negative_returns_zero():
    r = compute_kelly(KellyInput(
        capital=100000, entry_price=10,
        win_rate=30, avg_win=2, avg_loss=5,
    ))
    assert r.shares == 0
    assert r.warning is not None
    assert r.full_kelly_pct < 0
