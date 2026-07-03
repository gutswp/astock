import shutil
import subprocess
import time
from datetime import datetime

from rich.console import Console

from astock.render.tables import print_triggered_alerts
from astock.screen.alerts import check_watch, load_watchlist


def _osascript_notify(title: str, subtitle: str, message: str) -> None:
    if not shutil.which("osascript"):
        return
    script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception:
        pass


def _scan_all(notify: bool) -> list[dict]:
    watches = load_watchlist()
    if not watches:
        return []
    all_triggered: list[dict] = []
    for w in watches:
        try:
            hits = check_watch(w)
        except Exception:
            hits = []
        all_triggered.extend(hits)
    if notify and all_triggered:
        for t in all_triggered:
            _osascript_notify(
                title="AStock 预警",
                subtitle=f"{t['name']} ({t['code']})",
                message=t["message"],
            )
    return all_triggered


def run_watch(interval: int | None = None, notify: bool = True) -> None:
    console = Console()
    watches = load_watchlist()
    if not watches:
        console.print("[yellow]关注池为空。用 astock alert add 添加规则。[/yellow]")
        return

    if interval is None:
        console.print(f"[dim]单次扫描 {len(watches)} 只关注股...[/dim]")
        triggered = _scan_all(notify=notify)
        print_triggered_alerts(triggered)
        return

    console.print(f"[dim]循环扫描（间隔 {interval}s，Ctrl+C 停止），关注 {len(watches)} 只[/dim]")
    seen: set[tuple] = set()
    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            triggered = _scan_all(notify=notify)
            new_ones = []
            for t in triggered:
                key = (t["code"], t["type"], round(t["price"], 2))
                if key in seen:
                    continue
                seen.add(key)
                new_ones.append(t)
            if new_ones:
                console.print(f"[dim]{ts}[/dim]")
                print_triggered_alerts(new_ones)
            else:
                console.print(f"[dim]{ts} 无新触发（已见 {len(seen)} 条）[/dim]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]watch 停止[/dim]")
