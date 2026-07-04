import json
from datetime import datetime, timedelta

import pytest

from astock.portfolio import journal


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "trades.jsonl"
    monkeypatch.setattr(journal, "TRADES_PATH", p)
    return p


def _make(**overrides):
    base = dict(
        account="acct1", code="600000", name="A", action="buy",
        shares=100, price=10.0, note=None,
        prev_shares=0, prev_cost=0.0, new_shares=100, new_cost=10.0,
    )
    base.update(overrides)
    return base


def test_append_and_load(temp_journal):
    journal.append_trade(**_make())
    entries = journal.load_trades()
    assert len(entries) == 1
    assert entries[0]["code"] == "600000"


def test_filter_by_code(temp_journal):
    journal.append_trade(**_make(code="600000"))
    journal.append_trade(**_make(code="000001"))
    assert len(journal.load_trades(code="600000")) == 1
    assert len(journal.load_trades(code="999999")) == 0


def test_filter_by_account(temp_journal):
    journal.append_trade(**_make(account="a1"))
    journal.append_trade(**_make(account="a2"))
    assert len(journal.load_trades(account="a1")) == 1


def test_filter_by_days(temp_journal, monkeypatch):
    # 手写一条 10 天前的条目
    old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
    temp_journal.write_text(json.dumps({**_make(), "ts": old_ts}) + "\n", encoding="utf-8")
    journal.append_trade(**_make())  # today
    assert len(journal.load_trades(days=5)) == 1  # 只有 today
    assert len(journal.load_trades(days=30)) == 2
