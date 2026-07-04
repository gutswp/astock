import pandas as pd


def calc_ma(closes: pd.Series, period: int) -> pd.Series:
    return closes.rolling(window=period, min_periods=period).mean()


def calc_ema(closes: pd.Series, period: int) -> pd.Series:
    return closes.ewm(span=period, adjust=False).mean()


def calc_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return dif, dea, macd_hist


def detect_macd_golden_cross(closes: pd.Series) -> bool:
    if len(closes) < 35:
        return False
    dif, dea, _ = calc_macd(closes)
    if len(dif) < 2:
        return False
    return bool(dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] >= dea.iloc[-1])


def detect_ma_breakthrough(closes: pd.Series, period: int) -> bool:
    if len(closes) < period + 1:
        return False
    ma = calc_ma(closes, period)
    if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-2]):
        return False
    return bool(closes.iloc[-2] < ma.iloc[-2] and closes.iloc[-1] >= ma.iloc[-1])


def calc_volume_ratio(volumes: pd.Series, period: int = 5) -> float:
    if len(volumes) < period + 1:
        return 0.0
    avg_vol = volumes.iloc[-(period+1):-1].mean()
    if avg_vol == 0:
        return 0.0
    return float(volumes.iloc[-1] / avg_vol)


def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    diff = closes.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def detect_rsi_oversold_reversal(closes: pd.Series, period: int = 14) -> bool:
    """昨日 RSI<30 且今日 RSI 上穿 30（超卖反弹初现）."""
    if len(closes) < period + 2:
        return False
    rsi = calc_rsi(closes, period)
    if pd.isna(rsi.iloc[-1]) or pd.isna(rsi.iloc[-2]):
        return False
    return bool(rsi.iloc[-2] < 30 and rsi.iloc[-1] >= 30)


def calc_kdj(highs: pd.Series, lows: pd.Series, closes: pd.Series,
             n: int = 9, m1: int = 3, m2: int = 3) -> tuple[pd.Series, pd.Series, pd.Series]:
    low_n = lows.rolling(window=n, min_periods=n).min()
    high_n = highs.rolling(window=n, min_periods=n).max()
    rsv = (closes - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def detect_kdj_golden_cross(highs: pd.Series, lows: pd.Series, closes: pd.Series) -> bool:
    """KDJ 金叉：K 上穿 D，且 K < 50（低位金叉更有效）."""
    if len(closes) < 12:
        return False
    k, d, _ = calc_kdj(highs, lows, closes)
    if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-2]):
        return False
    return bool(k.iloc[-2] < d.iloc[-2] and k.iloc[-1] >= d.iloc[-1] and k.iloc[-1] < 50)


def calc_bollinger(closes: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = closes.rolling(window=period, min_periods=period).mean()
    std = closes.rolling(window=period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def detect_boll_lower_bounce(closes: pd.Series, period: int = 20) -> bool:
    """昨日收盘 < 下轨，今日收回下轨上方（下轨反弹）."""
    if len(closes) < period + 2:
        return False
    _, _, lower = calc_bollinger(closes, period)
    if pd.isna(lower.iloc[-1]) or pd.isna(lower.iloc[-2]):
        return False
    return bool(closes.iloc[-2] <= lower.iloc[-2] and closes.iloc[-1] > lower.iloc[-1])


# --- CCI --------------------------------------------------------------------

def calc_cci(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
    tp = (highs + lows + closes) / 3
    sma = tp.rolling(window=period, min_periods=period).mean()
    md = tp.rolling(window=period, min_periods=period).apply(
        lambda x: (x - x.mean()).abs().mean(), raw=False
    )
    return (tp - sma) / (0.015 * md.replace(0, pd.NA))


def detect_cci_oversold_reversal(highs: pd.Series, lows: pd.Series, closes: pd.Series,
                                  period: int = 14) -> bool:
    """昨日 CCI < -100，今日 CCI 上穿 -100."""
    if len(closes) < period + 2:
        return False
    cci = calc_cci(highs, lows, closes, period)
    if pd.isna(cci.iloc[-1]) or pd.isna(cci.iloc[-2]):
        return False
    return bool(cci.iloc[-2] < -100 and cci.iloc[-1] >= -100)


# --- OBV --------------------------------------------------------------------

def calc_obv(closes: pd.Series, volumes: pd.Series) -> pd.Series:
    diff = closes.diff()
    signed = volumes.where(diff > 0, -volumes.where(diff < 0, 0))
    return signed.fillna(0).cumsum()


# --- DMI / ADX --------------------------------------------------------------

def calc_dmi(highs: pd.Series, lows: pd.Series, closes: pd.Series,
             period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (+DI, -DI, ADX)."""
    high_diff = highs.diff()
    low_diff = -lows.diff()
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)

    prev_close = closes.shift(1)
    tr = pd.concat([
        (highs - lows),
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)

    import numpy as np
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    atr_safe = atr.replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return plus_di, minus_di, adx


def detect_dmi_golden_cross(highs: pd.Series, lows: pd.Series, closes: pd.Series,
                             period: int = 14, adx_min: float = 20.0) -> bool:
    """+DI 上穿 -DI 且 ADX ≥ adx_min（有趋势的多头开始）."""
    if len(closes) < period * 2 + 1:
        return False
    plus_di, minus_di, adx = calc_dmi(highs, lows, closes, period)
    if pd.isna(plus_di.iloc[-1]) or pd.isna(minus_di.iloc[-2]) or pd.isna(adx.iloc[-1]):
        return False
    crossed = plus_di.iloc[-2] < minus_di.iloc[-2] and plus_di.iloc[-1] >= minus_di.iloc[-1]
    return bool(crossed and adx.iloc[-1] >= adx_min)


# --- Parabolic SAR ----------------------------------------------------------

def calc_sar(highs: pd.Series, lows: pd.Series,
             af_step: float = 0.02, af_max: float = 0.2) -> tuple[pd.Series, pd.Series]:
    """返回 (sar 值, trend 序列)。trend=1 多头，-1 空头."""
    n = len(highs)
    sar = pd.Series([float("nan")] * n, index=highs.index)
    trend = pd.Series([0] * n, index=highs.index)
    if n < 2:
        return sar, trend

    # 用前两根初始化：假设初始为多头
    up = True
    ep = float(highs.iloc[0])
    af = af_step
    sar.iloc[0] = float(lows.iloc[0])
    trend.iloc[0] = 1

    for i in range(1, n):
        prev_sar = sar.iloc[i - 1]
        h_i, l_i = float(highs.iloc[i]), float(lows.iloc[i])
        # 前两根低/高的约束（多头 SAR 不能高于前 2 日最低；空头相反）
        prev_low_2 = min(float(lows.iloc[i - 1]),
                         float(lows.iloc[i - 2]) if i >= 2 else float(lows.iloc[i - 1]))
        prev_high_2 = max(float(highs.iloc[i - 1]),
                          float(highs.iloc[i - 2]) if i >= 2 else float(highs.iloc[i - 1]))
        if up:
            cur = prev_sar + af * (ep - prev_sar)
            cur = min(cur, prev_low_2)
            if l_i < cur:
                # 反转为空头
                up = False
                cur = ep  # 新 SAR 是原 EP
                ep = l_i
                af = af_step
            else:
                if h_i > ep:
                    ep = h_i
                    af = min(af + af_step, af_max)
        else:
            cur = prev_sar + af * (ep - prev_sar)
            cur = max(cur, prev_high_2)
            if h_i > cur:
                up = True
                cur = ep
                ep = h_i
                af = af_step
            else:
                if l_i < ep:
                    ep = l_i
                    af = min(af + af_step, af_max)
        sar.iloc[i] = cur
        trend.iloc[i] = 1 if up else -1
    return sar, trend


def detect_sar_bullish_flip(highs: pd.Series, lows: pd.Series) -> bool:
    """SAR 从空头翻多头（今日 trend=1 且昨日 trend=-1）."""
    if len(highs) < 3:
        return False
    _, trend = calc_sar(highs, lows)
    return bool(trend.iloc[-2] == -1 and trend.iloc[-1] == 1)
