import json
from datetime import datetime, timedelta
from pathlib import Path

from astock import DATA_DIR

TRADES_PATH = DATA_DIR / "trades.jsonl"


def append_trade(
    account: str,
    code: str,
    name: str,
    action: str,
    shares: int,
    price: float,
    note: str | None,
    prev_shares: int,
    prev_cost: float,
    new_shares: int,
    new_cost: float,
) -> None:
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "account": account,
        "code": code,
        "name": name,
        "action": action,
        "shares": shares,
        "price": price,
        "note": note,
        "prev_shares": prev_shares,
        "prev_cost": prev_cost,
        "new_shares": new_shares,
        "new_cost": new_cost,
    }
    with TRADES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_trades(
    code: str | None = None,
    account: str | None = None,
    days: int | None = None,
) -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    cutoff = None
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
    entries: list[dict] = []
    with TRADES_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if code and entry.get("code") != code:
                continue
            if account and entry.get("account") != account:
                continue
            if cutoff is not None:
                try:
                    ts = datetime.fromisoformat(entry.get("ts", ""))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
            entries.append(entry)
    return entries
