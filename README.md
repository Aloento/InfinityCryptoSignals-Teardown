# 把一个 Telegram 付费喊单频道拆开看

**中文** · [English](README.en.md) · [在线报告](index.html) · [English report](en/index.html)

我买了 **Infinity Signals VIP 💎** 的订阅（High Leverage / Long Term 两个频道），
但从来没用过。与其猜，不如把两个频道的**全部历史消息**抓下来，用交易所的分钟级 K 线逐笔重放一遍，
看看这些信号到底赚不赚钱。

结论：**不赚。**

| 频道 | 信号数 | 时间跨度 | 1x 单笔均值¹ | 单笔中位数 | 盈亏比 | 按宣传杠杆交易的爆仓率 |
|---|---|---|---|---|---|---|
| Infinity Signals VIP 💎 **High Leverage** | 7,790 | 2022-08 → 2026-11 | **−0.106%** | +0.124% | 0.868 | **69%** |
| Infinity Signals VIP 💎 **Long Term** | 19,219 | 2022-08 → 2026-11 | +0.173% | −1.046% | 1.048 | **61%** |

¹ 已扣手续费（开/平 5bp taker、止盈 2bp maker）与 1bp 滑点。

## 四个结论

1. **止损是装饰品。** 两个频道的止损价都恒定在开仓价 ±50%，四年不变，与杠杆完全无关。
   BTC 在 63,643 做空，止损写 95,560；78,025 做多，止损写 38,973。50 倍杠杆配 50% 的止损，
   等于没有止损。真正的出场规则是他们自己那句 `Use opposite signal as stop loss (Recommended)`
   —— 反向信号来了就翻仓，本仓库的回测就是这么撮合的。

2. **晒单是算术。** `Profit: 240% Target 4` 的真实含义是 `(TP4/Entry − 1) × 杠杆`。
   16,559 条盈利播报与该几何值的相关系数为 **0.9973**。它不是任何人的成交结果。

3. **方向判断没有信息量。** 把每条信号的方向随机翻转（止盈阶梯同步镜像，几何完全一致），
   时间、品种、翻仓节奏全不变，跑 8 组随机流：真实流单笔 −0.011%，随机流 +0.014% ± 0.015%，
   真实流只赢过 12% 的随机流。盈亏由「0.4% 止盈阶梯 + 反向翻仓」这套几何决定，而它的期望是负的。

4. **杠杆和风控互相矛盾。** 125 倍交叉盘，反向 0.4% 就强平；而它的止损在 −50% 之外。
   按它宣传的杠杆交易，69% 的单子会直接归零，单笔保证金平均 −23.4%。

Long Term 频道是个例外：单笔 +0.173%（t=2.58，自助法 95% 区间 +0.05%…+0.30%），
勉强算有微弱正期望。但中位数是 −1.05%，**全部利润来自最赚的 1% 交易**，
平均要同时持有 101 个品种（峰值 125），2022 年还是负的。它是彩票，不是策略；
再叠加它宣传的 20 倍杠杆，61% 的仓位会被强平。

## 仓库里有什么

```
index.html            中文报告（含全部图表）
en/index.html         English report
data/                 结构化后的信号与逐笔成交（含原始文本，CSV/JSONL，gzip）
scripts/              采集 → 解析 → 行情 → 撮合 → 出报告的完整流水线
```

### 数据

| 文件 | 内容 |
|---|---|
| `data/signals_high_leverage.csv.gz` | 7,790 条信号：品种、方向、杠杆、入场价、TP1–TP6、止损、**原始消息文本** |
| `data/signals_long_term.csv.gz` | 19,219 条信号，同上 |
| `data/trades_high_leverage.csv.gz` | 7,788 笔逐笔回测结果：成交价、出场时间、命中止盈数、单笔收益、最大浮亏 |
| `data/trades_long_term.csv.gz` | 18,914 笔，同上 |
| `data/raw_sample_*.jsonl.gz` | 每个频道最早 800 条原始消息（抓取格式示例） |

## 方法

- **采集**：Telethon 直连 MTProto，`messages.getHistory` 全量拉取，按消息 ID 续跑。
  两个频道共 148,308 条消息，一条未丢；同时记录 ID 空洞（= 被管理员删除的消息，
  High Leverage 缺 8,004 条 / 14.6%，Long Term 缺 19,454 条）。
- **解析**：模板固定，正则抽取字段；止盈播报、平仓通知、翻仓指令按回复链归属到具体信号。
- **行情**：Binance USDⓈ-M 合约 K 线，取自官方 `data.binance.vision` 月度打包文件
  （已下架品种也有历史，不存在幸存者偏差）。
- **撮合**：信号后第一根 1 分钟 K 线的开盘价市价成交（原话 `Enter as soonest possible`）；
  TP1–TP6 各减仓 1/6；剩余仓位在同品种下一条信号出现时平掉；
  同一根 K 线内止盈与反向同时出现时按不利方向先成交（悲观口径）。
- **杠杆档**：逐分钟检查最高/最低价是否触及强平价，维持保证金率 0.4%，单笔损失上限 100% 保证金。
- **零模型**：方向镜像测试，见上文结论 3。

## 复现

```bash
python scripts/scrape.py   --channel <channel_id>          # 全量抓取，可续跑
python scripts/parse.py    --channel <channel_id>          # 解析成结构化信号
python scripts/bulk.py     --from-signals <channel_id> --interval 1m
python scripts/backtest.py --channel <channel_id> --entry market --interval 1m
python scripts/benchmark.py --channel <channel_id> --seeds 8
python scripts/report.py                                   # 出中英双语报告
```

依赖：`telethon pandas numpy matplotlib pyarrow requests qrcode pillow`。

## 说明

- 数据来自我自己订阅的两个频道，消息本身是频道对所有人发布的公开内容。
- **已脱敏**：仓库里不含任何账号 ID、手机号、会话密钥或登录凭证，抓取用的授权会话未上传。
  频道名称保留，因为这是结论可被核对的唯一方式。
- 这是对一套商业信号服务的统计检验，不针对任何个人；所有结论都可以用 `data/` 里的逐笔数据复算。
- 不构成投资建议。
