from astock.tools.sizing import SizingInput, compute


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
