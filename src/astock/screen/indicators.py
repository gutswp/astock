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
