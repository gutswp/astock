from collections import defaultdict
from datetime import datetime

import anthropic
from rich.console import Console
from rich.markdown import Markdown

from astock import DATA_DIR
from astock.ai.client import make_client
from astock.config import AppConfig
from astock.data.provider import get_spot
from astock.portfolio.journal import load_trades

SYSTEM_PROMPT = """你是一位资深的交易复盘教练。用户会给你他过去 N 天的交易日志和当前持仓状态，你的任务是找出**可行动的模式**——哪些做对了、哪些做错了、下一步该改什么。

输出结构（Markdown）：

## 1. 概览
- 交易次数、涉及标的数、买入/卖出比
- 从数据看的整体交易风格（追涨/抄底/波段/长持）

## 2. 已实现盈亏（Realized）
按代码汇总卖出的实现盈亏，识别赚钱/亏钱的交易。

## 3. 未实现盈亏（Unrealized）
当前持仓的浮盈浮亏 top，标出问题标的。

## 4. 模式识别
从交易节奏、买入 note、加仓/减仓时点，找 2-3 个**具体**的模式（好的坏的都要）。
比如："在没有 note 的情况下买入的交易 X 笔全部亏损"，或"止损纪律差，浮亏 20%+ 才卖"。

## 5. 下一步改进
给 2-3 条**下次能立即执行**的具体改进（不是空话）。

要求：
- 用具体数字说话，不要空泛
- 直言不讳，但对严重错误也要指出深层原因（心态/纪律/研究不足）
- 用户是散户，主账户目前浮亏 15%+，复盘的目的是止血 + 建立纪律
"""


def _summarize_trades(trades: list[dict], current_spot: dict[str, float]) -> str:
    if not trades:
        return "（无交易记录）"

    by_code: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_code[t["code"]].append(t)

    lines = []
    for code, ts in sorted(by_code.items()):
        name = ts[0].get("name") or code
        buys = [t for t in ts if t["action"] == "buy"]
        sells = [t for t in ts if t["action"] == "sell"]
        total_buy_shares = sum(t["shares"] for t in buys)
        total_sell_shares = sum(t["shares"] for t in sells)
        avg_buy = (
            sum(t["shares"] * t["price"] for t in buys) / total_buy_shares
            if total_buy_shares else 0
        )
        avg_sell = (
            sum(t["shares"] * t["price"] for t in sells) / total_sell_shares
            if total_sell_shares else 0
        )
        realized = (avg_sell - avg_buy) * total_sell_shares if total_sell_shares else 0
        cur_price = current_spot.get(code, 0)
        remain = total_buy_shares - total_sell_shares
        unrealized = (cur_price - avg_buy) * remain if remain > 0 and cur_price else 0
        lines.append(
            f"### {code} {name}"
            f"\n- 交易次数: {len(ts)}（买 {len(buys)} / 卖 {len(sells)}）"
            f"\n- 累计买入 {total_buy_shares} 股，均价 {avg_buy:.2f}"
            f"\n- 累计卖出 {total_sell_shares} 股，均价 {avg_sell:.2f}"
            f"\n- 剩余持仓 {remain} 股，当前价 {cur_price:.2f}"
            f"\n- 已实现盈亏 {realized:+.2f}，浮动盈亏 {unrealized:+.2f}"
        )
        notes = [t.get("note") for t in ts if t.get("note")]
        if notes:
            lines.append("- 交易 note:")
            for n in notes:
                lines.append(f"  - {n}")

    return "\n".join(lines)


def _raw_trades_table(trades: list[dict], limit: int = 40) -> str:
    if not trades:
        return "（无）"
    tail = trades[-limit:]
    lines = ["| 时间 | 账户 | 方向 | 代码 | 名称 | 量 | 价 | 备注 |",
             "|---|---|---|---|---|---|---|---|"]
    for t in tail:
        lines.append(
            f"| {t.get('ts','')[:16]} | {t.get('account','')} | {t.get('action','')} | "
            f"{t.get('code','')} | {t.get('name','')} | {t.get('shares','')} | "
            f"{t.get('price',0):.2f} | {t.get('note') or ''} |"
        )
    return "\n".join(lines)


def _build_review_context(days: int) -> str | None:
    trades = load_trades(days=days)
    if not trades:
        return None
    codes = sorted({t["code"] for t in trades})
    spot = get_spot(codes) if codes else None
    current_spot: dict[str, float] = {}
    if spot is not None and not spot.empty:
        for _, r in spot.iterrows():
            current_spot[str(r["代码"]).zfill(6)] = float(r["最新价"])
    return (
        f"# 最近 {days} 天交易复盘数据\n\n"
        "## 按标的汇总\n\n"
        f"{_summarize_trades(trades, current_spot)}\n\n"
        "## 原始交易流水（最近 40 笔）\n\n"
        f"{_raw_trades_table(trades)}\n"
    )


def _save_review(review: str, days: int, context: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = DATA_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}.review.md"
    out_path.write_text(
        f"# AStock AI 复盘 {today}（回看 {days} 天）\n\n{review}\n\n---\n\n<details><summary>数据</summary>\n\n{context}\n\n</details>\n",
        encoding="utf-8",
    )
    return str(out_path)


def generate_review(config: AppConfig, days: int = 90) -> tuple[str, str] | None:
    """执行复盘，返回 (review_markdown, saved_path_str)。没有交易记录时返回 None."""
    context = _build_review_context(days)
    if context is None:
        return None

    client = make_client()
    response = client.messages.create(
        model=config.ai_model,
        max_tokens=max(config.ai_max_tokens, 3500),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    review = response.content[0].text
    path = _save_review(review, days, context)
    return review, path


def stream_review(config: AppConfig, days: int = 90):
    """流式复盘。yield (event, data)。"""
    try:
        yield ("stage", f"读取最近 {days} 天交易 + 拉价格")
        context = _build_review_context(days)
        if context is None:
            yield ("error", "暂无交易记录，等你记几笔再来。")
            return
        yield ("stage", "调用 AI 复盘")

        client = make_client()
        buf = []
        with client.messages.stream(
            model=config.ai_model,
            max_tokens=max(config.ai_max_tokens, 3500),
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        ) as stream:
            for text in stream.text_stream:
                buf.append(text)
                yield ("chunk", text)

        review = "".join(buf)
        path = _save_review(review, days, context)
        yield ("done", path)
    except Exception as e:
        yield ("error", str(e))


def run_review(config: AppConfig, days: int = 90) -> None:
    console = Console(width=110)
    console.print(f"[bold]== AI 交易复盘（最近 {days} 天） ==[/bold]")

    result = None
    try:
        result = generate_review(config, days=days)
    except anthropic.AuthenticationError:
        console.print("[red]API Key 无效或未设置[/red]")
        return
    if result is None:
        console.print("[yellow]暂无交易记录。等你用 buy/sell -n 记几笔之后再回来复盘吧。[/yellow]")
        return
    review, path = result
    console.print()
    console.print(Markdown(review))
    console.print()
    console.print(f"[green]复盘已保存: {path}[/green]")
