# 数据字典 / Data dictionary

所有时间均为 **UTC**。金额单位为该品种的报价货币（USDT）。

## signals_*.csv.gz

一行 = 频道里的一条开单信号。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int | Telegram 消息 ID（同频道内连续递增） |
| `dt` | ISO8601 | 消息发布时间（UTC） |
| `pair` | str | 规范化后的交易对，如 `BTCUSDT` |
| `dir` | `L` / `S` | 方向 |
| `leverage` | float | 频道自报杠杆（50 / 75 / 100 / 125，Long Term 固定 20） |
| `entry` | float | 频道报价的入场价 |
| `tp1` … `tp6` | float | 止盈档位（`Target7` 是 🚀，无固定价，不落库） |
| `sl` | float | 频道报价的止损价（NaN = 消息里写 `Defined Later`） |
| `text` | str | 原始消息全文 |

## trades_*.csv.gz

一行 = 回测引擎对一条信号的一次完整撮合。与 `signals` 通过 `id` 关联；
未成交 / 行情缺失 / 报价离谱的信号**不会**出现在这里（见 README 的剔除规则）。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int | 对应的信号消息 ID |
| `dt` | ISO8601 | 信号时间 |
| `pair` | str | 交易对 |
| `dir` | `L` / `S` | 方向 |
| `leverage` | float | 自报杠杆 |
| `entry_sig` | float | 频道报价的入场价（对照用） |
| `fill` | float | 实际成交价（下一根 1m 开盘价 ± 1bp 滑点） |
| `fill_dt` | ISO8601 | 成交时间 |
| `exit_dt` | ISO8601 | 最后一笔减仓的时间 |
| `hold_h` | float | 持仓小时数 |
| `tps` | int | 命中了几档止盈（0–6） |
| `reason` | str | 主导出场原因：`tp`（止盈打完）/ `flip`（反向翻仓） |
| `ret` | float | **1 倍名义收益**，已扣手续费，单位：小数（−0.0012 = −0.12%） |
| `ret_lev` | float | 按自报杠杆折算的保证金收益（该文件是 1x 回测，故与 `ret` 相同） |
| `mae` | float | 最大浮亏（持仓期内最不利价格相对入场价，小数，负数） |
| `mfe` | float | 最大浮盈，同上 |

## raw_sample_*.jsonl.gz

每个频道最早 800 条原始消息，`scrape.py` 的原样输出：

```json
{"id": 24, "date": "2022-08-29T10:55:02+00:00", "edit_date": null,
 "text": "📩Pair: XRPUSDT\n📈Direction: Long\n...", "post": true,
 "views": 7006, "forwards": 3, "grouped_id": null, "reply_to": null,
 "via_bot_id": null, "from_id": null, "media": null, "action": null}
```

`reply_to` 是信号归因的关键：止盈播报、平仓通知都回复到对应的开单消息上。

## 复算

```python
import pandas as pd
t = pd.read_csv("data/trades_high_leverage.csv.gz")
print(t["ret"].mean() * 100, (t["ret"] > 0).mean() * 100)
```
