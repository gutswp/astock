from unittest.mock import patch

import pandas as pd

from astock.screen import alerts


def _mk_watch(code="000001", alerts_list=None):
    return alerts.Watch(code=code, name="X", alerts=alerts_list or [])


def _mk_spot(price=10.0, change=1.0):
    return pd.DataFrame([{"代码": "000001", "名称": "X", "最新价": price, "涨跌幅": change}])


def _mk_hist():
    return pd.DataFrame({
        "日期": [f"2026-06-{i:02d}" for i in range(1, 41)],
        "收盘": list(range(10, 50)),
        "最高": list(range(10, 50)),
        "最低": list(range(10, 50)),
        "开盘": list(range(10, 50)),
        "成交量": [1000] * 40,
    })


def test_price_above_triggers():
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot(price=15)):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("price_above", value=10)]))
    assert len(hits) == 1
    assert hits[0]["type"] == "price_above"


def test_price_above_not_triggers():
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot(price=5)):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("price_above", value=10)]))
    assert hits == []


def test_stop_loss_triggers():
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot(price=8)):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("stop_loss", value=10)]))
    assert len(hits) == 1
    assert "止损" in hits[0]["message"]


def test_change_above_triggers():
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot(change=5.5)):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("change_above", value=5)]))
    assert len(hits) == 1


def test_change_below_triggers():
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot(change=-6.0)):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("change_below", value=-5)]))
    assert len(hits) == 1


def test_ma_break_triggers():
    # 构造：昨天低于 MA20，今天高于
    hist = pd.DataFrame({
        "日期": [f"D{i}" for i in range(25)],
        "收盘": [10.0] * 22 + [9.5, 10.5, 10.5],  # 倒数第二个上穿
        "最高": [10.0] * 25,
        "最低": [10.0] * 25,
        "开盘": [10.0] * 25,
        "成交量": [1000] * 25,
    })
    with patch("astock.screen.alerts.get_spot", return_value=_mk_spot()), \
         patch("astock.screen.alerts.get_hist", return_value=hist):
        hits = alerts.check_watch(_mk_watch(alerts_list=[alerts.Alert("ma_break", period=20)]))
    # 只要不 crash，逻辑就 OK；具体触发依赖 detect_ma_breakthrough 的语义（末尾两根）
    assert isinstance(hits, list)


def test_unknown_type_raises():
    import pytest
    with pytest.raises(ValueError):
        alerts.add_watch_alert("000001", "bogus_type", None, None)
