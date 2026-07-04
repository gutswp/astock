import pandas as pd

from astock.screen import indicators as ind


def test_ma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    ma3 = ind.calc_ma(s, 3)
    assert ma3.iloc[-1] == 4  # (3+4+5)/3
    assert pd.isna(ma3.iloc[0])


def test_macd_returns_three_series():
    s = pd.Series(range(50), dtype=float)
    dif, dea, hist = ind.calc_macd(s)
    assert len(dif) == 50 and len(dea) == 50 and len(hist) == 50


def test_macd_golden_cross_smoke():
    # 只验证函数不 crash + 返回 bool
    closes = pd.Series([10] * 20 + [9] * 10 + list(range(9, 30)), dtype=float)
    assert isinstance(ind.detect_macd_golden_cross(closes), bool)


def test_macd_golden_cross_false_on_flat():
    closes = pd.Series([10.0] * 40)
    assert ind.detect_macd_golden_cross(closes) is False


def test_ma_breakthrough_true():
    # 开始平稳站在均线上，末尾昨天低于MA、今天回到MA之上
    closes = pd.Series([10.0] * 20 + [9.5, 10.5])
    assert ind.detect_ma_breakthrough(closes, 5) is True


def test_ma_breakthrough_false_when_below():
    closes = pd.Series([10.0] * 20 + [9.5, 9.4])
    assert ind.detect_ma_breakthrough(closes, 5) is False


def test_volume_ratio():
    v = pd.Series([100, 100, 100, 100, 100, 300], dtype=float)
    assert ind.calc_volume_ratio(v, period=5) == 3.0


def test_rsi_range():
    # 加一次小回撤避免除零，保持整体上涨态势
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9.5, 11, 12, 13, 14, 15, 16], dtype=float)
    rsi = ind.calc_rsi(s)
    assert rsi.iloc[-1] > 70


def test_rsi_oversold_reversal_smoke():
    closes = pd.Series([100 - i * 2 for i in range(15)] + [72.0, 78.0], dtype=float)
    # 不同数据形态可能触发或不触发，只验证不 crash
    assert isinstance(ind.detect_rsi_oversold_reversal(closes), bool)


def test_kdj_shapes():
    highs = pd.Series(range(20), dtype=float)
    lows = pd.Series([x - 1 for x in range(20)], dtype=float)
    closes = pd.Series(range(20), dtype=float)
    k, d, j = ind.calc_kdj(highs, lows, closes)
    assert len(k) == 20 == len(d) == len(j)


def test_bollinger_bands():
    closes = pd.Series(range(30), dtype=float)
    u, m, l = ind.calc_bollinger(closes, period=20)
    assert not pd.isna(m.iloc[-1])
    assert u.iloc[-1] > m.iloc[-1] > l.iloc[-1]


def test_cci_bounds_relative():
    highs = pd.Series(range(1, 40), dtype=float)
    lows = pd.Series([x - 1 for x in range(1, 40)], dtype=float)
    closes = pd.Series(range(1, 40), dtype=float)
    cci = ind.calc_cci(highs, lows, closes, period=14)
    assert not pd.isna(cci.iloc[-1])


def test_cci_reversal_smoke():
    highs = pd.Series([10.0] * 30 + [5.0, 9.0])
    lows = pd.Series([9.0] * 30 + [4.0, 8.0])
    closes = pd.Series([9.5] * 30 + [4.5, 8.5])
    assert isinstance(ind.detect_cci_oversold_reversal(highs, lows, closes), bool)


def test_obv_direction():
    closes = pd.Series([10, 11, 10, 12, 11], dtype=float)
    volumes = pd.Series([100, 200, 150, 300, 100], dtype=float)
    obv = ind.calc_obv(closes, volumes)
    # 第一根 diff 是 NaN → 0；第二根 +200；第三根 -150；第四根 +300；第五根 -100
    assert obv.iloc[-1] == 200 - 150 + 300 - 100


def test_dmi_shapes():
    highs = pd.Series(range(1, 40), dtype=float)
    lows = pd.Series([x - 1 for x in range(1, 40)], dtype=float)
    closes = pd.Series(range(1, 40), dtype=float)
    plus, minus, adx = ind.calc_dmi(highs, lows, closes)
    assert len(plus) == len(minus) == len(adx)


def test_sar_shapes():
    highs = pd.Series([10 + i * 0.1 for i in range(30)])
    lows = pd.Series([9 + i * 0.1 for i in range(30)])
    sar, trend = ind.calc_sar(highs, lows)
    assert len(sar) == 30
    assert set(trend.unique()) <= {0, 1, -1}


def test_sar_flip_smoke():
    highs = pd.Series([10 + i * 0.1 for i in range(20)] + [11.5, 10.5, 9.5])
    lows = pd.Series([9 + i * 0.1 for i in range(20)] + [10.0, 9.0, 8.0])
    assert isinstance(ind.detect_sar_bullish_flip(highs, lows), bool)
