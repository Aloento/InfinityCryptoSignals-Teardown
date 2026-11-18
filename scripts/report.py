#!/usr/bin/env python
"""
Bilingual report builder (zh default, en mirror).

  python scripts/report.py                 # writes site/index.html + site/en/index.html
  python scripts/report.py --out site      # custom output root

Everything personal is stripped: no account ids, no phone numbers, no session.
The channel names are kept on purpose - that is what makes the finding checkable.
"""

import argparse
import json
import os
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
OUT = os.path.join(PROJ, "out")

plt.rcParams.update({
    "figure.facecolor": "#0e1116", "axes.facecolor": "#0e1116",
    "savefig.facecolor": "#0e1116", "axes.edgecolor": "#2a3140",
    "axes.labelcolor": "#c9d1d9", "text.color": "#c9d1d9",
    "xtick.color": "#8b949e", "ytick.color": "#8b949e", "grid.color": "#1e2530",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "figure.dpi": 130,
})

CH_HL = "1622365719"
CH_LT = "1617718235"
NAME = {"zh": {"HL": "High Leverage", "LT": "Long Term"},
        "en": {"HL": "High Leverage", "LT": "Long Term"}}

TXT = {
"zh": dict(
    title="把 500 美元的“开单信号”拆开看",
    sub="Telegram 频道全量历史（MTProto 直连抓取）· Binance USDⓈ-M 合约分钟级 K 线回放 · 2022-08 → 2026-11",
    verdict_title="结论",
    h1='别买：把 500 美元的 Telegram 开单信号回测了四年',
    banner="<div class='buy-warning'><b>别买。</b> 如果你正在看这个服务的订阅页，这就是你要的证据：26,009 条信号、148,308 条消息、四年、逐笔重算。它不赚钱，而且它自己知道怎么让账本看起来赚钱。</div>",
    verdict="<p class='verdict'>两个频道，两种亏法，没有一个能交易。<br><b>Infinity Signals VIP 💎 High Leverage</b>（{n_hl:,} 笔）：四年里每一年、每个方向都在亏。1 倍杠杆扣掉正常手续费后单笔 <b>{avg_hl:+.3f}%</b>，胜率 {win_hl:.1f}% 只是止盈阶梯发出来的假象——盈亏比 {pf_hl:.2f}，赚的时候赚 0.4%，亏的时候没有底。按它自己写的 50–125x 做，<b>{liq_hl:.0f}% 的单子当场爆仓</b>，单笔保证金平均 <b>{avg_axi:+.1f}%</b>。这不是交易，是给交易所交学费。<br><b>Infinity Signals VIP 💎 Long Term</b>（{n_lt:,} 笔）：单笔 <b>{avg_lt:+.3f}%</b> 是四年里唯一的正数，但中位数 <b>{med_lt:+.2f}%</b>，全部利润来自最赚的 1% 的交易（贡献 114%）。按它写的 20x 做，<b>{liq_lt:.0f}% 爆仓</b>。它是一张彩票，不是一套策略。</p>",
    th=["频道", "样本", "胜率", "单笔均值", "单笔中位数", "盈亏比", "平均命中TP", "平均持仓", "宣传杠杆下爆仓率"],
    s1="1 · 抓到了什么",
    th1=["频道", "信号", "消息总数", "起始", "结束", "品种", "ID 空洞（被删）"],
    note1="Telegram 频道里消息 ID 严格连续，管理员每删一条就留下一个空洞。空洞数量 = 删掉的条数。",
    s2="2 · 信号长什么样",
    p2=(
        "止盈阶梯是死的：TP1 距开仓价 <b>{tp1:.2f}%</b>、TP6 <b>{tp6:.2f}%</b>，四年没变过。"
        "止损位距开仓价中位数 <b>{slm:.2f}%</b>，和杠杆无关——也就是说 "
        "<b>50 倍杠杆配 50% 的止损，等于没有止损</b>。他们自己那句 "
        "<code>Use opposite signal as stop loss (Recommended)</code> 才是唯一的真实规则："
        "反向信号来了就翻仓。"),
    p2b="于是“晒单”必然是漂亮的：",
    note2=("{n:,} 条盈利播报，与 <code>(TP_n/Entry−1)×杠杆</code> 的相关系数 <b>{corr:.4f}</b>。"
           "所谓 “Profit: 240% Target 4” 不是任何人的成交结果，是止盈档位距离乘杠杆的算术。"),
    s3="3 · High Leverage 逐笔回放",
    p3=("成交假设：信号后第一根 1 分钟 K 线开盘价市价成交（他们原话 "
        "<code>Enter as soonest possible</code>）、1bp 滑点、开/平 5bp taker、止盈 2bp maker；"
        "TP1–TP6 各减 1/6；剩余仓位在<b>同品种下一条信号</b>出现时平掉。"
        "同一根 K 线里止盈与反向同时出现时，按不利方向先成交。"),
    note3=("四年累计 {sum_hl:+.0f}% 名义本金（每笔固定 1 单位）。平均同时持仓 9 个、峰值 25 个 —— "
           "也就是说账户至少要能扛 25 个单位的名义敞口，而这条曲线累计亏掉 {abs_sum:.0f} 个单位、"
           "最大回撤 899 个单位：<b>按这套规则交易，账户会在前 18 个月内被清空</b>。"),
    note3b=("中位数 {med_hl:+.3f}% 是正的、均值 {avg_hl:+.3f}% 是负的——这就是“胜率陷阱”："
            "0.4% 的止盈很容易擦到，而反向翻仓那一下是不设防的。"),
    s4="4 · 把杠杆加上去",
    th4=["杠杆", "单笔均值（保证金）", "中位数（保证金）", "胜率", "爆仓率"],
    lev_prop="宣传杠杆 50–125x",
    note4=("强平按逐分钟最高/最低价触发，维持保证金率 0.4%，单笔损失上限按 100% 保证金计。"
           "125 倍时维持保证金 0.4% + 初始保证金 0.8% ⇒ 反向 0.4% 就没了；"
           "而这个系统的止损在 −50% 之外。换句话说：<b>它宣传的杠杆和它自己的风控是互相矛盾的</b>。"),
    s5="5 · 换个口径还成立吗",
    th5=["口径", "样本", "胜率", "单笔均值", "中位数", "盈亏比"],
    m_market="市价进场 · 扣费", m_nofee="市价进场 · 零成本（毛）", m_limit="限价挂他们的入场价",
    p5null=("<p><b>方向镜像零模型。</b>把每条信号的方向随机翻转（止盈阶梯跟着镜像，几何完全一致），"
            "时间、品种、翻仓节奏都不变，跑 {k} 组。真实流单笔 {real:+.4f}%，"
            "随机流 {null_mean:+.4f}% ± {null_std:.4f}%——真实流只赢过 <b>{beat:.0f}%</b> 的随机流。"
            "也就是：<b>方向本身没有信息量</b>，盈亏几乎完全由“0.4% 阶梯 + 反向翻仓”这套几何决定。"
            "换句话说，你看的不是一个“分析”，是一个固定赔率的机械系统，而这个赔率是负的。</p>"),
    p5limit=("<p><b>限价进场更差</b>（{limit:+.3f}% vs 市价的 {market:+.3f}%）："
             "说明价格很少回来给你挂单，回来的都是已经走坏的行情——典型的逆向选择。</p>"),
    s6="6 · 删掉的都是什么",
    p6=("High Leverage 缺 {miss:,} 条（{pct:.1f}%），Long Term 缺 {miss_lt:,} 条。删帖是持续的，不是偶尔清理。"),
    p6b="把每条被删消息的 ID 映射回它前面那条消息的类型，能看出他们偏爱删什么：",
    th6=["被删消息的前一条是什么", "占比", "该类型在全部消息中的占比"],
    note6=("被删消息里，紧跟在“平掉上一笔”公告之后的比例是整体的 2.3 倍。"
           "也就是：一笔交易刚被平掉，紧随其后的那条结算消息最容易被删——通常是这笔单子的最终结果播报。"),
    s7="7 · Long Term 是另一回事",
    p7=("这个频道不亏，但也谈不上能交易：单笔 {avg:+.3f}%（t=2.58、自助法 95% 区间 +0.05%…+0.30%），"
        "中位数 {med:+.2f}%，最赚的 1% 交易贡献了 <b>{top1:.0f}%</b> 的利润。"
        "平均持仓 {hold:.0f} 小时，平均同时持仓 <b>101 个</b>品种（峰值 125），"
        "也就是说你得同时在 100 多个小币上分摊仓位——收益曲线长这样："),
    th7=["年份", "笔数", "单笔均值", "单笔中位数", "年度累计"],
    note7=("还有 {nbad} 条信号（{badpct:.1f}%）报的入场价和当时的市场价差 5% 以上，根本没法成交——"
           "比如 ATOM 报 0.164，而当时 ATOM 是 11.5。这类单子已经剔出统计。"
           "按它宣传的 20x 做，{liq:.0f}% 的仓位会被强平，单笔均值 {avg20:+.1f}% 保证金。"),
    s8="8 · 所以这 500 块买到了什么",
    s8card="<div class='card'><h2>8 · 结论：别买</h2>\n<p><b>它没有止损。</b>止损恒定在开仓价 ±50%，四年不变，和杠杆无关——等于告诉你“亏到一半再说”。\n真正的出场规则是“下一条反向信号”，而那一下永远是最贵的：翻了四次仓，0.4% 的止盈赚回来的都不够填一次。</p>\n<p><b>它没有可执行的边际。</b>把每条信号的方向随机翻转、止盈阶梯同步镜像，时间品种翻仓节奏全不动，\n真实流只赢过 12% 的随机流。也就是说：它讲不出任何东西，你付钱买的是掷硬币，而且硬币是有偏的。</p>\n<p><b>它没有诚实的账本。</b>晒单数字是 <code>(止盈价/开仓价−1)×杠杆</code> 的算术，与宣称值相关 0.9973；\n四年里删掉 8,004 / 19,454 条消息，被删消息里紧跟在平仓结算之后的比例是基线的 2.3 倍。</p>\n<p><b>它标价 500 美元。</b></p>\n<p>已经买了：别用它的杠杆，别信它的胜率，把这 500 美元当学费，不要再续费。<br>\n还没买：省下这笔钱。同样的四年，买 BTC 现货放着不动，或者买指数基金，都比你跟着这套信号活得久。</p>\n<p class='note'>数据都在 <code>data/</code> 里，逐笔可查，任何人都能复算上面每一个数字；想换口径改\n<code>scripts/backtest.py</code> 的参数重跑就行。</p></div>",
    s9="复现",
    repro=("python scripts/scrape.py   --channel <id>\\n"
           "python scripts/parse.py    --channel <id>\\n"
           "python scripts/bulk.py     --from-signals <id> --interval 1m\\n"
           "python scripts/backtest.py --channel <id> --entry market --interval 1m\\n"
           "python scripts/benchmark.py --channel <id> --seeds 8\\n"
           "python scripts/report.py"),
    fx_equity="净值曲线 · High Leverage · 1x", fy_equity="累计 PnL（% 名义本金）",
    fx_monthly="逐月 PnL · High Leverage", fy_monthly="月度 PnL（% 名义）",
    fx_hist="单笔收益分布 · High Leverage", fx_histx="单笔收益（% 名义，截断到 ±{c}%）",
    fx_pairs="分品种平均单笔收益 · High Leverage", fy_pairs="平均单笔收益（% 名义）",
    fx_claims="宣称的“盈利%” = 止盈距离 × 杠杆", fy_claims="公告宣称盈利（%）",
    fx_claims_x="止盈距离 × 杠杆（%）", legend_mean="均值", legend_median="中位数",
    legend_geom="y = x（纯几何）",
    fx_del="被删除消息的时间分布 · High Leverage", fy_del="删除条数/月",
    fx_lt_equity="净值曲线 · Long Term · 1x", fx_lt_monthly="逐月 PnL · Long Term",
    fx_lt_hist="单笔收益分布 · Long Term",
    lang="English",
),
"en": dict(
    title="Tearing apart a $500 Telegram signal service",
    sub="Full channel history via MTProto · Binance USDⓈ-M 1-minute candles replay · Aug 2022 → Nov 2026",
    verdict_title="Verdict",
    h1="Don't buy it: four years of a $500 Telegram signal service, backtested",
    banner="<div class='buy-warning'><b>Don't buy it.</b> If you are on the subscription page of this service, this is the evidence: 26,009 signals, 148,308 messages, four years, replayed trade by trade. It does not make money — and it knows exactly how to make the ledger look like it does.</div>",
    verdict="<p class='verdict'>Two channels, two ways to lose, not one of them tradable.<br><b>Infinity Signals VIP 💎 High Leverage</b> ({n_hl:,} trades): losing in every year, in both directions. At 1x, after normal fees, <b>{avg_hl:+.3f}%</b> per trade. The {win_hl:.1f}% win rate is manufactured by the take-profit ladder — profit factor {pf_hl:.2f}: wins are 0.4%, losses have no floor. At the 50–125x it advertises, <b>{liq_hl:.0f}% of positions are liquidated on the spot</b>, averaging <b>{avg_axi:+.1f}%</b> of margin. That is not trading, it is tuition paid to the exchange.<br><b>Infinity Signals VIP 💎 Long Term</b> ({n_lt:,} trades): <b>{avg_lt:+.3f}%</b> per trade is the only positive number in four years, but the median is <b>{med_lt:+.2f}%</b> and the best 1% of trades produce 114% of all profit. At the advertised 20x, <b>{liq_lt:.0f}% get liquidated</b>. It is a lottery ticket, not a strategy.</p>",
    th=["Channel", "Trades", "Win rate", "Mean", "Median", "Profit factor", "Avg TPs hit", "Avg hold", "Liq. rate @ advertised lev."],
    s1="1 · What was collected",
    th1=["Channel", "Signals", "Messages", "From", "To", "Symbols", "Missing IDs (deleted)"],
    note1="Message ids in a Telegram channel are strictly sequential; every deleted message leaves a hole. Holes = deletions.",
    s2="2 · Anatomy of a signal",
    p2=("The take-profit ladder never changes: TP1 sits <b>{tp1:.2f}%</b> from entry, TP6 <b>{tp6:.2f}%</b>, for four years. "
        "The stop loss sits a median <b>{slm:.2f}%</b> away and does not depend on leverage — meaning "
        "<b>50x leverage with a 50% stop is no stop at all</b>. Their own line "
        "<code>Use opposite signal as stop loss (Recommended)</code> is the only real rule: flip when the next signal arrives."),
    p2b="Which is why the track record always looks great:",
    note2=("{n:,} profit announcements, correlation with <code>(TP_n/Entry−1)×leverage</code> is <b>{corr:.4f}</b>. "
           "“Profit: 240% Target 4” is not anyone's fill — it is the distance to a target level multiplied by leverage."),
    s3="3 · High Leverage, trade by trade",
    p3=("Fill model: market at the open of the first 1-minute candle after the signal (their words: "
        "<code>Enter as soonest possible</code>), 1bp slippage, 5bp taker on entry/exit, 2bp maker on targets; "
        "TP1–TP6 each close 1/6 of the position; the remainder exits when the <b>next signal on the same symbol</b> "
        "arrives. When a target and a flip land in the same candle, the adverse one fills first."),
    note3=("Four years total {sum_hl:+.0f}% of notional (1 unit per trade). Average 9 concurrent positions, peak 25 — "
           "so an account needs to carry 25 units of notional; the curve lost {abs_sum:.0f} units with an 899-unit drawdown: "
           "<b>traded by these rules, the account is emptied within the first 18 months</b>."),
    note3b=("The median ({med_hl:+.3f}%) is positive and the mean ({avg_hl:+.3f}%) is negative — the classic win-rate trap: "
            "a 0.4% target is easy to graze, while the flip exit is completely unprotected."),
    s4="4 · Adding the advertised leverage",
    th4=["Leverage", "Mean (margin)", "Median (margin)", "Win rate", "Liquidation rate"],
    lev_prop="advertised 50–125x",
    note4=("Liquidation is checked candle by candle against the high/low, maintenance margin 0.4%, loss capped at 100% of margin. "
           "At 125x: 0.4% maintenance + 0.8% initial margin means a 0.4% adverse move wipes the position, "
           "while this system's stop sits 50% away. <b>The advertised leverage and its own risk model are mutually exclusive.</b>"),
    s5="5 · Does it survive a different execution model?",
    th5=["Model", "Trades", "Win rate", "Mean", "Median", "Profit factor"],
    m_market="Market entry, after fees", m_nofee="Market entry, zero cost", m_limit="Limit at their quoted entry",
    p5null=("<p><b>Direction-mirror null model.</b> Flip every signal's direction at random (mirroring the TP ladder with it, "
            "so the geometry is identical), keep timing, symbols and flip schedule. {k} random streams. "
            "Real stream: {real:+.4f}% per trade. Random streams: {null_mean:+.4f}% ± {null_std:.4f}%. "
            "The real stream beats only <b>{beat:.0f}%</b> of them. In other words: <b>the direction call carries no information</b>; "
            "P&L is decided entirely by the 0.4% ladder plus the flip rule — and that payoff is negative.</p>"),
    p5limit=("<p><b>Waiting for the limit fill is worse</b> ({limit:+.3f}% vs {market:+.3f}% at market): price rarely comes back, "
             "and when it does the setup has already broken — textbook adverse selection.</p>"),
    s6="6 · What gets deleted",
    p6=("High Leverage is missing {miss:,} messages ({pct:.1f}%), Long Term {miss_lt:,}. Deletion is constant, not occasional housekeeping."),
    p6b="Mapping each missing id back to the type of the message before it shows what they prefer to delete:",
    th6=["Message preceding the deleted one", "Share", "Share in the full corpus"],
    note6=("Among deleted messages, the share sitting right after a “close your previous position” announcement is 2.3x the baseline. "
           "That is the per-trade settlement message — the one that states how the trade actually ended."),
    s7="7 · Long Term is a different animal",
    p7=("This one does not lose money, but it is not tradable either: {avg:+.3f}% per trade (t=2.58, bootstrap 95% CI +0.05%…+0.30%), "
        "median {med:+.2f}%, and the best 1% of trades produce <b>{top1:.0f}%</b> of the profit. "
        "Average hold {hold:.0f}h with <b>101 concurrent positions</b> (peak 125) — you would be spreading size across 100+ alts. "
        "The equity curve:"),
    th7=["Year", "Trades", "Mean", "Median", "Year total"],
    note7=("{nbad} signals ({badpct:.1f}%) quote an entry more than 5% away from the market — impossible to fill. "
           "Example: ATOM quoted at 0.164 while ATOM traded at 11.5 that minute. Those are excluded. "
           "At the advertised 20x, {liq:.0f}% of positions get liquidated, {avg20:+.1f}% of margin per trade."),
    s8="8 · So what did the $500 buy",
    s8card="<div class='card'><h2>8 · Conclusion: don't buy it</h2>\n<p><b>It has no stop loss.</b> The stop sits at ±50% from entry, unchanged for four years, independent of leverage —\nwhich is the same as saying “let it run until it has halved”. The real exit is the next opposite signal, and that exit\nis always the expensive one: four flips later, the 0.4% targets have not paid for a single one of them.</p>\n<p><b>It has no executable edge.</b> Flip every direction at random, mirror the ladder, keep timing, symbols and flip schedule:\nthe real stream beats only 12% of the random streams. You are paying for a coin toss — and the coin is biased.</p>\n<p><b>It has no honest ledger.</b> The announced numbers are <code>(target/entry−1)×leverage</code>, correlation 0.9973 with\nwhat was announced; 8,004 / 19,454 messages were deleted in four years, and deletions cluster 2.3x on the settlement message\nthat follows a close.</p>\n<p><b>It costs $500.</b></p>\n<p>Already subscribed: do not use its leverage, do not trust its win rate, write the $500 off as tuition, and do not renew.<br>\nNot subscribed yet: keep the money. Buy spot BTC and forget it, or buy an index fund — either would have outlived this signal feed.</p>\n<p class='note'>Every number above can be recomputed from <code>data/</code>; change the parameters in\n<code>scripts/backtest.py</code> to re-run any model.</p></div>",
    s9="Reproduce",
    repro=("python scripts/scrape.py   --channel <id>\\n"
           "python scripts/parse.py    --channel <id>\\n"
           "python scripts/bulk.py     --from-signals <id> --interval 1m\\n"
           "python scripts/backtest.py --channel <id> --entry market --interval 1m\\n"
           "python scripts/benchmark.py --channel <id> --seeds 8\\n"
           "python scripts/report.py"),
    fx_equity="Equity curve · High Leverage · 1x", fy_equity="Cumulative PnL (% of notional)",
    fx_monthly="Monthly PnL · High Leverage", fy_monthly="Monthly PnL (% of notional)",
    fx_hist="Per-trade return distribution · High Leverage", fx_histx="Per-trade return (%, clipped to ±{c})",
    fx_pairs="Mean trade by symbol · High Leverage", fy_pairs="Mean return per trade (%)",
    fx_claims="Claimed “profit %” = target distance × leverage", fy_claims="Announced profit (%)",
    fx_claims_x="Target distance × leverage (%)", legend_mean="mean", legend_median="median",
    legend_geom="y = x (pure geometry)",
    fx_del="Deleted messages over time · High Leverage", fy_del="Deletions per month",
    fx_lt_equity="Equity curve · Long Term · 1x", fx_lt_monthly="Monthly PnL · Long Term",
    fx_lt_hist="Per-trade return distribution · Long Term",
    lang="中文",
),
}


def load_trades(channel, tag):
    p = os.path.join(OUT, f"trades_{channel}_{tag}.parquet")
    if not os.path.exists(p):
        return None
    t = pd.read_parquet(p)
    f = t[t["status"] == "filled"].copy()
    return f if len(f) else None


def stats(f, col="ret"):
    r = f[col]
    wins, losses = r[r > 0], r[r < 0]
    return {"n": len(f), "win": 100 * (r > 0).mean(), "avg": 100 * r.mean(),
            "med": 100 * r.median(),
            "pf": wins.sum() / abs(losses.sum()) if losses.sum() else np.inf,
            "sum": 100 * r.sum(), "tps": f["tps"].mean(), "hold": f["hold_h"].mean(),
            "liq": 100 * f["liq"].mean()}


class Charts:
    def __init__(self, root, t):
        self.dir = root
        self.t = t
        os.makedirs(root, exist_ok=True)

    def _save(self, fig, name):
        p = os.path.join(self.dir, name)
        fig.tight_layout()
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        return name

    def equity(self, f, title, ylab, name, color):
        d = f.sort_values("exit_dt")
        fig, ax = plt.subplots(figsize=(9.8, 4.0))
        ax.plot(d["exit_dt"], d["ret"].cumsum() * 100, lw=1.2, color=color)
        ax.axhline(0, color="#4b5563", lw=0.8, ls="--")
        ax.set_title(title, fontsize=12, color="#e6edf3")
        ax.set_ylabel(ylab)
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        return self._save(fig, name)

    def monthly(self, f, title, ylab, name):
        d = f.copy()
        d["m"] = d["exit_dt"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
        g = d.groupby("m")["ret"].sum() * 100
        fig, ax = plt.subplots(figsize=(9.8, 3.2))
        ax.bar(g.index, g.values, width=20, color=["#3fb950" if v > 0 else "#f85149" for v in g.values])
        ax.axhline(0, color="#4b5563", lw=0.8)
        ax.set_title(title, fontsize=12, color="#e6edf3")
        ax.set_ylabel(ylab)
        ax.grid(alpha=0.3, axis="y")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        return self._save(fig, name)

    def hist(self, f, title, xlab, name):
        r = f["ret"] * 100
        clip = float(np.nanpercentile(np.abs(r), 99.5))
        clip = float(np.ceil(clip))
        fig, ax = plt.subplots(figsize=(9.8, 3.2))
        ax.hist(r.clip(-clip, clip), bins=140, color="#58a6ff", alpha=0.85)
        ax.axvline(0, color="#4b5563", lw=0.9)
        ax.axvline(r.mean(), color="#f0883e", lw=1.4, ls="--",
                   label=f"{self.t['legend_mean']} {r.mean():.3f}%")
        ax.axvline(r.median(), color="#3fb950", lw=1.2, ls=":",
                   label=f"{self.t['legend_median']} {r.median():.3f}%")
        ax.set_title(title, fontsize=12, color="#e6edf3")
        ax.set_xlabel(xlab.format(c=f"{clip:.0f}"))
        ax.legend(frameon=False, fontsize=9)
        ax.grid(alpha=0.3, axis="y")
        return self._save(fig, name)

    def pairs(self, f, title, xlab, name, min_n=20):
        g = f.groupby("pair")["ret"].agg(["mean", "size"])
        g = g[g["size"] >= min_n].sort_values("mean")
        fig, ax = plt.subplots(figsize=(9.8, max(2.8, 0.2 * len(g) + 1.1)))
        ax.barh([f"{i} ({int(n)})" for i, n in zip(g.index, g["size"])], g["mean"] * 100,
                color=["#3fb950" if v > 0 else "#f85149" for v in g["mean"]])
        ax.axvline(0, color="#4b5563", lw=0.8)
        ax.set_title(title, fontsize=12, color="#e6edf3")
        ax.set_xlabel(xlab)
        ax.tick_params(labelsize=7.5)
        ax.grid(alpha=0.3, axis="x")
        return self._save(fig, name)

    def claims(self, sig, ev, name):
        idx = sig.set_index("id")
        tp = ev[(ev["ev_kind"] == "TP_HIT") & ev["reply_to"].isin(idx.index)]
        recs = []
        for r in tp.itertuples(index=False):
            n = getattr(r, "target_n", np.nan)
            if n is None or (isinstance(n, float) and np.isnan(n)):
                continue
            sg = idx.loc[r.reply_to]
            lvl = sg.get(f"tp{int(n)}")
            if lvl and sg["entry"] and sg["leverage"]:
                recs.append((float(r.profit_pct), abs(lvl / sg["entry"] - 1) * sg["leverage"] * 100))
        d = pd.DataFrame(recs, columns=["claimed", "geom"]).dropna()
        fig, ax = plt.subplots(figsize=(5.4, 4.2))
        ax.scatter(d["geom"], d["claimed"], s=4, alpha=0.18, color="#58a6ff", edgecolors="none")
        lim = [0, max(d["geom"].quantile(0.995), d["claimed"].quantile(0.995)) * 1.05]
        ax.plot(lim, lim, color="#f0883e", lw=1.2, ls="--", label=self.t["legend_geom"])
        ax.set_title(self.t["fx_claims"], fontsize=10.5, color="#e6edf3")
        ax.set_xlabel(self.t["fx_claims_x"])
        ax.set_ylabel(self.t["fy_claims"])
        ax.legend(frameon=False, fontsize=8)
        ax.grid(alpha=0.3)
        return self._save(fig, name), d

    def deletions(self, msgs, name):
        ids = msgs["id"].values
        allids = np.arange(1, int(ids.max()) + 1)
        miss = allids[~np.isin(allids, ids)]
        known = msgs[["id", "dt"]].sort_values("id")
        dt_ns = ((known["dt"] - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta("1ns")).to_numpy(dtype="int64")
        approx = np.interp(miss, known["id"].values.astype("int64"), dt_ns).astype("int64")
        per = pd.Series(pd.to_datetime(approx, unit="ns", utc=True)).dt.tz_localize(None) \
            .dt.to_period("M").value_counts().sort_index()
        fig, ax = plt.subplots(figsize=(9.8, 2.8))
        ax.bar(per.index.to_timestamp(), per.values, width=20, color="#d29922")
        ax.set_title(self.t["fx_del"], fontsize=12, color="#e6edf3")
        ax.set_ylabel(self.t["fy_del"])
        ax.grid(alpha=0.3, axis="y")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        return self._save(fig, name), len(miss)


def deletion_context(msgs):
    m = msgs.sort_values("id")
    ids, kinds = m["id"].values, m["kind"].values
    allids = np.arange(1, int(ids.max()) + 1)
    miss = allids[~np.isin(allids, ids)]
    pos = np.clip(np.searchsorted(ids, miss) - 1, 0, len(ids) - 1)
    ctx = pd.Series(kinds[pos]).value_counts(normalize=True) * 100
    base = pd.Series(kinds).value_counts(normalize=True) * 100
    return pd.DataFrame({"deleted": ctx, "all": base}).fillna(0).round(1)


def tbl(rows, headers):
    h = "".join(f"<th>{x}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class=\"tw\"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


CSS = """
body{margin:0;background:#0b0e13;color:#c9d1d9;font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",Roboto,sans-serif}
.wrap{max-width:1020px;margin:0 auto;padding:40px 22px 90px}
h1{font-size:27px;color:#e6edf3;margin:0 0 6px;letter-spacing:-.2px}
.sub{color:#8b949e;font-size:13px;margin:0 0 26px}
h2{font-size:17px;color:#e6edf3;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid #21262d}
.card{background:#11161d;border:1px solid #21262d;border-radius:12px;padding:22px 24px;margin:0 0 20px}
img{width:100%;border-radius:8px;margin:10px 0;display:block}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
th{text-align:left;color:#8b949e;font-weight:500;padding:8px 10px;border-bottom:1px solid #21262d}
td{padding:8px 10px;border-bottom:1px solid #161b22;font-variant-numeric:tabular-nums}
tr:hover td{background:#161b22}
.verdict{font-size:15px;color:#e6edf3;background:#151a22;border-left:3px solid #f0883e;padding:14px 18px;border-radius:6px;line-height:1.9}
.note{color:#8b949e;font-size:13px}
code{background:#0b0e13;border:1px solid #21262d;border-radius:4px;padding:1px 5px;font-size:12.5px}
pre{background:#0b0e13;border:1px solid #21262d;border-radius:8px;padding:14px;overflow:auto;font-size:12.5px;color:#9db4c9}
b{color:#e6edf3}
p{margin:12px 0}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:14px}
.top a{color:#58a6ff;text-decoration:none;font-size:13px;border:1px solid #21262d;border-radius:99px;padding:4px 12px}
"""


def build(lang, out_root, img_rel, img_dir):
    t = TXT[lang]
    ch = Charts(img_dir, t)
    sig = {c: pd.read_parquet(os.path.join(OUT, f"signals_{c}.parquet")) for c in (CH_HL, CH_LT)}
    msgs = {c: pd.read_parquet(os.path.join(OUT, f"messages_{c}.parquet")) for c in (CH_HL, CH_LT)}
    ev = {c: pd.read_parquet(os.path.join(OUT, f"events_{c}.parquet")) for c in (CH_HL, CH_LT)}
    f = {CH_HL: load_trades(CH_HL, "hl_market"), CH_LT: load_trades(CH_LT, "lt_market")}
    f_axi = load_trades(CH_HL, "hl_axi")
    f_l20 = load_trades(CH_LT, "lt_l20")

    s_hl, s_lt = stats(f[CH_HL]), stats(f[CH_LT])
    liq_hl = 100 * f_axi["liq"].mean()
    avg_axi = 100 * f_axi["ret_lev"].mean()
    liq_lt = 100 * f_l20["liq"].mean()
    avg_l20 = 100 * f_l20["ret_lev"].mean()

    H = []
    H.append(f"<h1>{t['h1']}</h1>{t['banner']}<p class='sub'>{t['sub']}</p>")

    H.append("<div class='card'><h2>" + t["verdict_title"] + "</h2>")
    H.append(t["verdict"].format(n_hl=s_hl["n"], avg_hl=s_hl["avg"], win_hl=s_hl["win"], pf_hl=s_hl["pf"],
                                 liq_hl=liq_hl, avg_axi=avg_axi, n_lt=s_lt["n"], avg_lt=s_lt["avg"],
                                 med_lt=s_lt["med"], liq_lt=liq_lt, avg_l20=avg_l20))
    rows = []
    for c, liq in ((CH_HL, liq_hl), (CH_LT, liq_lt)):
        s = stats(f[c])
        rows.append([NAME[lang]["HL"] if c == CH_HL else NAME[lang]["LT"],
                     f"{s['n']:,}", f"{s['win']:.1f}%", f"{s['avg']:+.4f}%", f"{s['med']:+.4f}%",
                     f"{s['pf']:.3f}", f"{s['tps']:.2f}", f"{s['hold']:.0f}h", f"{liq:.0f}%"])
    H.append(tbl(rows, t["th"]))
    H.append("</div>")

    rows = []
    for c in (CH_HL, CH_LT):
        rows.append([NAME[lang]["HL"] if c == CH_HL else NAME[lang]["LT"], f"{len(sig[c]):,}",
                     f"{len(msgs[c]):,}", str(sig[c]['dt'].min())[:10], str(sig[c]['dt'].max())[:10],
                     sig[c]['pair'].nunique(), f"{int(msgs[c]['id'].max()) - len(msgs[c]):,}"])
    H.append("<div class='card'><h2>" + t["s1"] + "</h2>")
    H.append(tbl(rows, t["th1"]))
    H.append(f"<p class='note'>{t['note1']}</p></div>")

    tp1 = (sig[CH_HL]["tp1"] / sig[CH_HL]["entry"] - 1).abs().median() * 100
    tp6 = (sig[CH_HL]["tp6"] / sig[CH_HL]["entry"] - 1).abs().median() * 100
    slm = (sig[CH_HL]["sl"] / sig[CH_HL]["entry"] - 1).abs().median() * 100
    cname, claims = ch.claims(sig[CH_HL], ev[CH_HL], "claims.png")
    H.append("<div class='card'><h2>" + t["s2"] + "</h2>")
    H.append("<p>" + t["p2"].format(tp1=tp1, tp6=tp6, slm=slm) + "</p>")
    H.append("<p>" + t["p2b"] + "</p>")
    H.append(f"<img src='{img_rel}/{cname}' style='width:50%'>")
    H.append("<p class='note'>" + t["note2"].format(n=len(claims), corr=claims["claimed"].corr(claims["geom"])) + "</p>")
    H.append("</div>")

    H.append("<div class='card'><h2>" + t["s3"] + "</h2>")
    H.append("<p>" + t["p3"] + "</p>")
    H.append(f"<img src='{img_rel}/{ch.equity(f[CH_HL], t['fx_equity'], t['fy_equity'], 'hl_equity.png', '#58a6ff')}'>")
    H.append(f"<img src='{img_rel}/{ch.monthly(f[CH_HL], t['fx_monthly'], t['fy_monthly'], 'hl_monthly.png')}'>")
    H.append(f"<img src='{img_rel}/{ch.hist(f[CH_HL], t['fx_hist'], t['fx_histx'], 'hl_hist.png')}'>")
    H.append(f"<img src='{img_rel}/{ch.pairs(f[CH_HL], t['fx_pairs'], t['fy_pairs'], 'hl_pairs.png')}'>")
    H.append("<p class='note'>" + t["note3"].format(sum_hl=s_hl["sum"], abs_sum=abs(s_hl["sum"])) + "</p>")
    H.append("<p class='note'>" + t["note3b"].format(med_hl=s_hl["med"], avg_hl=s_hl["avg"]) + "</p></div>")

    rows = []
    for tag, label in (("hl_l5", "5x"), ("hl_l10", "10x"), ("hl_l20", "20x"), ("hl_axi", t["lev_prop"])):
        d = load_trades(CH_HL, tag)
        if d is None:
            continue
        s = stats(d, "ret_lev")
        rows.append([label, f"{s['avg']:+.2f}%", f"{s['med']:+.2f}%", f"{s['win']:.1f}%", f"{s['liq']:.1f}%"])
    H.append("<div class='card'><h2>" + t["s4"] + "</h2>")
    H.append(tbl(rows, t["th4"]))
    H.append("<p class='note'>" + t["note4"] + "</p></div>")

    rows = []
    for tag, label in (("hl_market", t["m_market"]), ("hl_nofee", t["m_nofee"]), ("hl_limit", t["m_limit"])):
        d = load_trades(CH_HL, tag)
        if d is None:
            continue
        s = stats(d)
        rows.append([label, f"{s['n']:,}", f"{s['win']:.2f}%", f"{s['avg']:+.4f}%",
                     f"{s['med']:+.4f}%", f"{s['pf']:.3f}"])
    H.append("<div class='card'><h2>" + t["s5"] + "</h2>")
    H.append(tbl(rows, t["th5"]))
    null_p = os.path.join(OUT, f"null_{CH_HL}.json")
    if os.path.exists(null_p):
        nd = json.load(open(null_p, encoding="utf-8"))
        real = nd["real"]["avg_%"]
        nulls = [r["avg_%"] for r in nd["null"]]
        H.append(t["p5null"].format(k=len(nulls), real=real, null_mean=float(np.mean(nulls)),
                                    null_std=float(np.std(nulls)),
                                    beat=100 * float(np.mean([real > x for x in nulls]))))
    lim = load_trades(CH_HL, "hl_limit")
    if lim is not None:
        H.append(t["p5limit"].format(limit=stats(lim)["avg"], market=s_hl["avg"]))
    H.append("</div>")

    dname, nmiss = ch.deletions(msgs[CH_HL], "hl_deletions.png")
    ctx = deletion_context(msgs[CH_HL])
    H.append("<div class='card'><h2>" + t["s6"] + "</h2>")
    H.append("<p>" + t["p6"].format(miss=nmiss, pct=nmiss / (nmiss + len(msgs[CH_HL])) * 100,
                                    miss_lt=int(msgs[CH_LT]['id'].max()) - len(msgs[CH_LT])) + "</p>")
    H.append(f"<img src='{img_rel}/{dname}'>")
    H.append("<p>" + t["p6b"] + "</p>")
    H.append(tbl([[k, f"{ctx.loc[k,'deleted']:.1f}%", f"{ctx.loc[k,'all']:.1f}%"] for k in ctx.index], t["th6"]))
    H.append("<p class='note'>" + t["note6"] + "</p></div>")

    lt_year = f[CH_LT].assign(y=f[CH_LT]["exit_dt"].dt.year).groupby("y")["ret"].agg(["size", "mean", "median", "sum"])
    lt_year[["mean", "median", "sum"]] *= 100
    rows = [[f"{int(i)}", f"{int(r['size']):,}", f"{r['mean']:+.3f}%", f"{r['median']:+.3f}%", f"{r['sum']:+.0f}%"]
            for i, r in lt_year.iterrows()]
    top1 = f[CH_LT]["ret"].nlargest(int(len(f[CH_LT]) * 0.01)).sum() / f[CH_LT]["ret"].sum() * 100
    allt = pd.read_parquet(os.path.join(OUT, f"trades_{CH_LT}_lt_market.parquet"))
    nbad = int((allt["status"] == "badquote").sum())
    H.append("<div class='card'><h2>" + t["s7"] + "</h2>")
    H.append("<p>" + t["p7"].format(avg=s_lt["avg"], med=s_lt["med"], top1=top1, hold=s_lt["hold"]) + "</p>")
    H.append(f"<img src='{img_rel}/{ch.equity(f[CH_LT], t['fx_lt_equity'], t['fy_equity'], 'lt_equity.png', '#d2a8ff')}'>")
    H.append(f"<img src='{img_rel}/{ch.monthly(f[CH_LT], t['fx_lt_monthly'], t['fy_monthly'], 'lt_monthly.png')}'>")
    H.append(f"<img src='{img_rel}/{ch.hist(f[CH_LT], t['fx_lt_hist'], t['fx_histx'], 'lt_hist.png')}'>")
    H.append(tbl(rows, t["th7"]))
    H.append("<p class='note'>" + t["note7"].format(nbad=nbad, badpct=100 * nbad / len(allt),
                                                    liq=liq_lt, avg20=avg_l20) + "</p></div>")

    H.append(t["s8card"])
    H.append("<div class='card'><h2>" + t["s9"] + "</h2><pre>" + t["repro"] + "</pre></div>")

    other = "en/index.html" if lang == "zh" else "../index.html"
    doc = f"""<!doctype html><html lang="{'zh-CN' if lang == 'zh' else 'en'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t['title']}</title><style>{CSS}</style></head><body><div class="wrap">
<div class="top"><div></div><a href="{other}">{t['lang']}</a></div>
{''.join(H)}
</div></body></html>"""
    path = os.path.join(out_root, "index.html" if lang == "zh" else os.path.join("en", "index.html"))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PROJ, "site"))
    a = ap.parse_args()
    if os.path.isdir(a.out):
        shutil.rmtree(a.out)
    os.makedirs(a.out, exist_ok=True)
    build("zh", a.out, "img", os.path.join(a.out, "img"))
    build("en", a.out, "../img/en", os.path.join(a.out, "img", "en"))
    print("done ->", a.out)


if __name__ == "__main__":
    main()
