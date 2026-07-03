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
