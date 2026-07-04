import anthropic
from rich.console import Console
from rich.markdown import Markdown

from astock.ai.client import make_client
from astock.config import AppConfig
from astock.data.provider import get_hist, get_spot, get_news

SYSTEM_PROMPT = """你是一位专业的 A 股投资分析师。你的任务是基于提供的股票数据（行情、技术指标、新闻）给出客观、专业的分析。

分析框架：
1. **当前状态**：股价位置、趋势方向、关键支撑/压力位
2. **技术面**：均线系统、MACD、量价关系
3. **消息面**：相关新闻/公告的影响分析（如有）
4. **风险提示**：主要风险因素
5. **操作建议**：明确的持有/买入/卖出/观望建议，附简要理由

要求：
- 用中文回答
- 简洁直接，不要空泛套话
- 给出具体的价格参考（支撑位、压力位）
- 如果是持仓股，要考虑成本价给出建议"""


def _build_stock_context(code: str, config: AppConfig) -> str:
    parts = []

    # 实时行情
    spot = get_spot([code])
    if not spot.empty:
        row = spot.iloc[0]
        parts.append(f"股票: {row['名称']} ({code})")
        parts.append(f"最新价: {row['最新价']}  今日涨跌: {row['涨跌幅']:.2f}%")

    # 检查是否是持仓股
    for acct in config.accounts:
        for h in acct.holdings:
            if h.code == code:
                parts.append(f"持仓信息: {h.shares}股 成本{h.cost} 账户{acct.name}")

    # 历史K线
    hist = get_hist(code, 60)
    if not hist.empty:
        recent = hist.tail(10)
        parts.append("\n近10日K线:")
        for _, r in recent.iterrows():
            parts.append(
                f"  {r['日期']}  开{r['开盘']:.2f} 收{r['收盘']:.2f} "
                f"高{r['最高']:.2f} 低{r['最低']:.2f} 量{int(r['成交量'])}"
            )

        closes = hist["收盘"].astype(float)
        for ma_period in [5, 10, 20, 60]:
            if len(closes) >= ma_period:
                ma_val = closes.tail(ma_period).mean()
                parts.append(f"MA{ma_period}: {ma_val:.2f}")

    # 新闻
    try:
        news = get_news(code)
        if not news.empty:
            parts.append("\n近期新闻:")
            for _, n in news.head(5).iterrows():
                title = n.get("新闻标题", n.get("title", ""))
                time_str = n.get("发布时间", n.get("publish_time", ""))
                if title:
                    parts.append(f"  [{time_str}] {title}")
    except Exception:
        pass

    return "\n".join(parts)


def generate_analysis(code: str, config: AppConfig) -> str:
    """执行单股 AI 分析，返回 markdown 文本."""
    code = code.zfill(6)
    context = _build_stock_context(code, config)
    client = make_client()
    response = client.messages.create(
        model=config.ai_model,
        max_tokens=config.ai_max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"请分析以下股票:\n\n{context}"}],
    )
    return response.content[0].text


def analyze_stock(code: str, config: AppConfig) -> None:
    console = Console(width=100)
    code = code.zfill(6)
    console.print(f"[dim]正在分析 {code}...[/dim]")
    try:
        result = generate_analysis(code, config)
    except anthropic.AuthenticationError:
        console.print("[red]API Key 无效或未设置[/red]")
        return
    console.print()
    console.print(Markdown(result))
    console.print()
