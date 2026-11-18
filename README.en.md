# Don't buy it: four years of a paid Telegram signal channel

[中文](README.md) · **English** · [Chinese report](https://aloento.github.io/InfinityCryptoSignals-Teardown/) · [English report](https://aloento.github.io/InfinityCryptoSignals-Teardown/en/)

> **If you are thinking about subscribing to Infinity Signals VIP: don't.**
> What follows is 26,009 signals, 148,308 messages, four years, replayed trade by trade.
> It does not make money — and it knows exactly how to make the ledger look like it does.

I pulled the **entire message history** of both channels and replayed every signal against exchange
minute candles.

| Channel | Signals | Period | Mean per trade (1x)¹ | Median | Profit factor | Liquidation rate at advertised leverage |
|---|---|---|---|---|---|---|
| Infinity Signals VIP 💎 **High Leverage** | 7,790 | Aug 2022 → Nov 2026 | **−0.106%** | +0.124% | 0.868 | **69%** |
| Infinity Signals VIP 💎 **Long Term** | 19,219 | Aug 2022 → Nov 2026 | +0.173% | −1.046% | 1.048 | **61%** |

¹ net of fees (5bp taker on entry/exit, 2bp maker on targets) and 1bp slippage.

## Four findings

1. **It has no stop loss.** In both channels the stop sits exactly ±50% from entry, unchanged for four
   years, independent of leverage. Short BTC at 63,643 with a stop at 95,560; long at 78,025 with a stop at
   38,973. 50x leverage with a 50% stop is the same as saying "let it run until it has halved". The real
   exit rule is their own line `Use opposite signal as stop loss (Recommended)` — flip when the next signal
   arrives, and that exit is always the expensive one.

2. **It has no honest ledger.** `Profit: 240% Target 4` means `(TP4/Entry − 1) × leverage`. Across 16,559
   profit announcements the correlation with that geometric value is **0.9973**. It is not anyone's fill;
   it is the distance to a target level multiplied by leverage.

3. **It has no executable edge.** Flip every signal's direction at random (mirroring the TP ladder so the
   geometry is identical), keep timing, symbols and flip schedule, and run 8 random streams: real stream
   −0.011% per trade, random streams +0.014% ± 0.015%. The real stream beats only 12% of them. You are
   paying for a coin toss — and the coin is biased.

4. **Its leverage contradicts its risk model.** At 125x cross, a 0.4% adverse move liquidates; their stop
   sits 50% away. Trading at the advertised leverage liquidates 69% of positions, averaging −23.4% of margin
   each. That is not trading, it is tuition paid to the exchange.

*Long Term* is the only positive number: +0.173% per trade (t=2.58, bootstrap 95% CI +0.05%…+0.30%).
But the median is −1.05%, **the best 1% of trades produce all of the profit**, it holds 101 concurrent
positions on average (peak 125), and 2022 was negative. At its advertised 20x, 61% of positions get
liquidated. It is a lottery ticket, not a strategy.

## What is in this repo

```
index.html            Chinese report (all charts)
en/index.html         English report
data/                 parsed signals and per-trade results (with raw message text), gzipped
scripts/              the full pipeline: scrape → parse → klines → backtest → report
```

### Data

| File | Contents |
|---|---|
| `data/signals_high_leverage.csv.gz` | 7,790 signals: symbol, direction, leverage, entry, TP1–TP6, stop, **raw message text** |
| `data/signals_long_term.csv.gz` | 19,219 signals, same schema |
| `data/trades_high_leverage.csv.gz` | 7,788 simulated trades: fill, exit time, TPs hit, return, max adverse excursion |
| `data/trades_long_term.csv.gz` | 18,914 simulated trades, same schema |
| `data/raw_sample_*.jsonl.gz` | the first 800 raw messages per channel (scraper output format) |

## Method

- **Collection**: Telethon over MTProto, `messages.getHistory`, resumable by message id. 148,308 messages,
  none missed. Message-id holes are recorded too — those are admin deletions (8,004 in High Leverage = 14.6%,
  19,454 in Long Term).
- **Parsing**: the template is fixed, so fields are extracted by regex; TP announcements, close notifications
  and flip commands are attached to signals through the reply chain.
- **Prices**: Binance USDⓈ-M klines from the official `data.binance.vision` dumps — delisted symbols included,
  so there is no survivorship bias.
- **Execution**: market at the open of the first 1-minute candle after the signal (their words:
  `Enter as soonest possible`); TP1–TP6 each close 1/6; the remainder exits on the next signal for the same
  symbol; when a target and a flip land in the same candle, the adverse one fills first.
- **Leverage**: liquidation checked candle by candle against high/low, maintenance margin 0.4%, loss capped
  at 100% of margin.
- **Null model**: the direction-mirror test described in finding 3.

## Reproduce

```bash
python scripts/scrape.py   --channel <channel_id>
python scripts/parse.py    --channel <channel_id>
python scripts/bulk.py     --from-signals <channel_id> --interval 1m
python scripts/backtest.py --channel <channel_id> --entry market --interval 1m
python scripts/benchmark.py --channel <channel_id> --seeds 8
python scripts/report.py
```

Dependencies: `telethon pandas numpy matplotlib pyarrow requests qrcode pillow`.

## Notes

- The data is content these two channels broadcast to all members. **De-identified**: no account ids, phone
  numbers, session keys or credentials are in this repo — the authorised scraping session is not uploaded.
  The channel names are kept because that is the only way the finding can be checked.
- This is a statistical test of a commercial signal service. Every number can be recomputed from the files in
  `data/`; if you get a different answer, open an issue — the data is public.
- Not investment advice. But if the question is "should I renew", the answer is no.
