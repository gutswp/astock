import json

import pandas as pd

from astock.data import cache
from astock.data.http import SINA_HEADERS, curl_get, retry

SPOT_TTL = 60
HIST_TTL = 86400
INDUSTRY_TTL = 604800

SINA_SPOT_URL = "https://hq.sinajs.cn/list="

__all__ = [
    "SINA_HEADERS",  # re-export for backwards-compat
    "get_spot",
    "get_all_spot",
    "get_hist",
    "get_fund_flow",
    "get_sector_flow",
    "get_industry",
    "get_news",
]


def _code_to_sina(code: str) -> str:
    code = code.zfill(6)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "2", "3")):
        return f"sz{code}"
    elif code.startswith("1"):  # ETF on SZ
        return f"sz{code}"
    elif code.startswith("5"):  # ETF on SH
        return f"sh{code}"
    return f"sz{code}"


def _parse_sina_line(line: str) -> dict | None:
    if "=" not in line or '""' in line:
        return None
    var_part, data_part = line.split("=", 1)
    sina_code = var_part.split("_")[-1]
    code = sina_code[2:]
    data = data_part.strip().strip('";').split(",")
    if len(data) < 32:
        return None
    return {
        "代码": code,
        "名称": data[0],
        "开盘": float(data[1]) if data[1] else 0,
        "昨收": float(data[2]) if data[2] else 0,
        "最新价": float(data[3]) if data[3] else 0,
        "最高": float(data[4]) if data[4] else 0,
        "最低": float(data[5]) if data[5] else 0,
        "成交量": int(float(data[8])) if data[8] else 0,
        "成交额": float(data[9]) if data[9] else 0,
        "日期": data[30] if len(data) > 30 else "",
    }


@retry
def get_spot(codes: list[str]) -> pd.DataFrame:
    key = f"spot_{'_'.join(sorted(codes))}"
    cached = cache.get(key, SPOT_TTL)
    if cached is not None:
        return pd.DataFrame(cached)

    sina_codes = [_code_to_sina(c) for c in codes]
    url = SINA_SPOT_URL + ",".join(sina_codes)
    raw = curl_get(url, SINA_HEADERS, encoding="gbk")

    records = []
    for line in raw.strip().split("\n"):
        parsed = _parse_sina_line(line)
        if parsed and parsed["最新价"] > 0:
            parsed["涨跌幅"] = round((parsed["最新价"] - parsed["昨收"]) / parsed["昨收"] * 100, 3) if parsed["昨收"] else 0
            records.append(parsed)

    if records:
        cache.put(key, records)
    return pd.DataFrame(records)


@retry
def get_all_spot() -> pd.DataFrame:
    key = "all_spot"
    cached = cache.get(key, SPOT_TTL)
    if cached is not None:
        return pd.DataFrame(cached)
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        records = df.to_dict("records")
        cache.put(key, records)
        return df
    except Exception:
        raise ConnectionError(
            "AKShare 全市场行情获取失败（东方财富 API 可能不稳定）。"
            "scan 命令需要全市场数据，请稍后重试。"
        )


@retry
def get_hist(code: str, days: int = 120) -> pd.DataFrame:
    key = f"hist_{code}_{days}"
    cached = cache.get(key, HIST_TTL)
    if cached is not None:
        return pd.DataFrame(cached)

    # 用新浪日线接口: money.finance.sina.com.cn
    market = "sh" if code.startswith(("6", "9", "5")) else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/"
        f"json_v2.php/CN_MarketData.getKLineData?"
        f"symbol={market}{code}&scale=240&ma=no&datalen={days}"
    )
    raw = curl_get(url, SINA_HEADERS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse history for {code}")

    records = []
    for item in data:
        records.append({
            "日期": item["day"],
            "开盘": float(item["open"]),
            "收盘": float(item["close"]),
            "最高": float(item["high"]),
            "最低": float(item["low"]),
            "成交量": int(item["volume"]),
        })

    if records:
        cache.put(key, records)
    return pd.DataFrame(records)


def get_fund_flow(code: str) -> pd.DataFrame:
    key = f"flow_{code}"
    cached = cache.get(key, HIST_TTL)
    if cached is not None:
        return pd.DataFrame(cached)
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow(stock=code, market="")
        if not df.empty:
            records = df.tail(10).to_dict("records")
            cache.put(key, records)
        return df
    except Exception:
        return pd.DataFrame()


def get_sector_flow() -> pd.DataFrame:
    key = "sector_flow"
    cached = cache.get(key, SPOT_TTL * 5)
    if cached is not None:
        return pd.DataFrame(cached)
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        records = df.to_dict("records")
        cache.put(key, records)
        return df
    except Exception:
        return pd.DataFrame()


def _em_secid(code: str) -> str:
    code = code.zfill(6)
    if code.startswith(("5", "6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def get_industry(code: str) -> str:
    key = f"industry_{code}"
    cached = cache.get(key, INDUSTRY_TTL)
    if cached is not None:
        return cached.get("industry", "未知")

    # ETF/LOF 无行业分类，直接标记
    if code.zfill(6).startswith(("1", "5")):
        cache.put(key, {"industry": "ETF/基金"})
        return "ETF/基金"

    try:
        url = (
            f"https://push2delay.eastmoney.com/api/qt/stock/get?"
            f"fltt=2&invt=2&fields=f127&secid={_em_secid(code)}"
        )
        raw = curl_get(url, timeout=8)
        data = json.loads(raw).get("data") or {}
        industry = data.get("f127") or ""
        if industry and industry != "-":
            cache.put(key, {"industry": industry})
            return industry
    except Exception:
        pass
    return "未知"


def get_news(code: str) -> pd.DataFrame:
    try:
        import akshare as ak
        return ak.stock_news_em(symbol=code)
    except Exception:
        return pd.DataFrame()


# 主要指数：上证/深证/创业板/沪深300/科创50
_INDEX_SPEC = [
    ("1.000001", "上证指数"),
    ("0.399001", "深证成指"),
    ("0.399006", "创业板指"),
    ("1.000300", "沪深300"),
    ("1.000688", "科创50"),
]


def get_indices() -> pd.DataFrame:
    key = "indices"
    cached = cache.get(key, SPOT_TTL)
    if cached is not None:
        return pd.DataFrame(cached)

    records = []
    for secid, name in _INDEX_SPEC:
        try:
            url = (
                f"https://push2delay.eastmoney.com/api/qt/stock/get?"
                f"fltt=2&invt=2&fields=f43,f169,f170,f47&secid={secid}"
            )
            raw = curl_get(url, timeout=8)
            data = json.loads(raw).get("data") or {}
            if not data:
                continue
            records.append({
                "名称": name,
                "代码": secid.split(".")[1],
                "最新价": float(data.get("f43") or 0),
                "涨跌额": float(data.get("f169") or 0),
                "涨跌幅": float(data.get("f170") or 0),
                "成交量": int(data.get("f47") or 0),
            })
        except Exception:
            continue

    if records:
        cache.put(key, records)
    return pd.DataFrame(records)
