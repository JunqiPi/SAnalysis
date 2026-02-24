# 📡 妖股选股团队 — 数据基础设施完整指南

> **核心原则**：数据质量决定策略上限。垃圾数据进 = 垃圾决策出。
> **日期**：2026年2月

---

## 一、按团队拆解的数据需求清单

### 🔴 空仓挤压狙击队需要什么数据？

| 数据类型 | 具体字段 | 更新频率 | 延迟容忍度 |
|----------|----------|----------|------------|
| Short Interest (空仓股数) | 总空仓量、Short Float %、变化趋势 | 官方：每月2次 / 估算：每日 | 2周(官方) / 当日(估算) |
| Days to Cover | Short Interest ÷ ADTV | 每日 | 当日 |
| Cost to Borrow (借券费率) | 年化借券利率、可借券数量 | 实时-每日 | 小时级 |
| Securities Lending数据 | 在贷股数、利用率(Utilization) | 每日 | 当日 |
| Float数据 | 流通股数、内部人持股、机构持股 | 季度（13F/SC-13D） | 周级 |
| Put/Call Ratio | 标的级别的看跌/看涨比率 | 每日 | 当日 |

### 🟠 Gamma挤压猎手需要什么数据？

| 数据类型 | 具体字段 | 更新频率 | 延迟容忍度 |
|----------|----------|----------|------------|
| 完整期权链 | 所有行权价的Bid/Ask/Last/Volume/OI/Greeks | 实时 | **分钟级** |
| Gamma Exposure (GEX) | 各行权价的净Gamma、翻转点(Flip) | 盘中实时 | 分钟级 |
| 异常期权活动 | 大单(Block)、扫单(Sweep)、单笔>$100K | 实时 | **秒级** |
| Dark Pool数据 | 暗池成交量、大宗交易 | 盘后 | 当日 |
| 隐含波动率 | IV、IV Rank、IV Percentile、IV Skew | 实时 | 分钟级 |
| Open Interest变化 | 逐日OI变化(区分新建vs平仓) | 每日 | 当日 |

### 🟡 社交情绪侦察队需要什么数据？

| 数据类型 | 具体字段 | 更新频率 | 延迟容忍度 |
|----------|----------|----------|------------|
| Reddit帖子/评论 | 文本、upvotes、评论数、subreddit | 实时流式 | <5分钟 |
| Twitter/X帖子 | 文本、转发、点赞、作者粉丝数 | 实时流式 | <5分钟 |
| StockTwits | 情绪标签(Bullish/Bearish)、消息量 | 实时 | <5分钟 |
| Google Trends | 搜索量指数、突增检测 | 每日(免费)/小时级(付费) | 小时级 |
| 新闻API | 标题、正文、情绪评分 | 实时 | 分钟级 |

### 🟢 低流通放量突破特战队需要什么数据？

| 数据类型 | 具体字段 | 更新频率 | 延迟容忍度 |
|----------|----------|----------|------------|
| 实时行情 | OHLCV(1分钟/5分钟/日线) | 实时 | **秒级** |
| Float/流通股 | 精确流通股数、限售股解禁日 | 每日 | 当日 |
| 相对成交量(RVOL) | 当前量 vs 30/90日均量倍数 | 实时计算 | 分钟级 |
| 技术指标 | MA、RSI、VWAP、OBV、ATR、布林带 | 实时计算 | 分钟级 |
| 盘前/盘后数据 | Pre-market gappers、AH异动 | 实时 | 分钟级 |
| 关键价位 | 52周高低、历史支撑阻力 | 每日 | 当日 |

### 🔵 动量+催化复合精英队需要什么数据？

| 数据类型 | 具体字段 | 更新频率 | 延迟容忍度 |
|----------|----------|----------|------------|
| 历史价格(3-12月) | 日线OHLCV、复权价格 | 每日 | 当日 |
| 财经日历 | 财报日期、FDA日期、经济数据发布 | 每日 | 当日 |
| 分析师一致预期 | EPS预期、营收预期、修正方向 | 每日 | 当日 |
| 财务数据 | 营收、净利润、自由现金流、增速 | 季度 | 周级 |
| VIX/市场宽度 | VIX指数、涨跌家数比、新高新低比 | 实时 | 分钟级 |
| SEC Filing | 13F、SC-13D/G、内部人买卖 | 不定期 | 当日 |

---

## 二、数据源分级评估（准确性 × 成本 × 可用性）

### 🏆 Tier 1：机构级数据（最准确，成本最高）

| 平台 | 核心优势 | 价格 | 准确度 | 适合谁 |
|------|----------|------|--------|--------|
| **ORTEX** | 空仓数据行业标杆，97%准确率预测交易所报告数据。覆盖7万+证券，实时估算Short Interest，含借券费、利用率、在贷股数 | Basic $39/月, Advanced $129/月 | ★★★★★ | 空仓挤压团队首选 |
| **S3 Partners** (via FactSet) | 独立空仓数据+证券融资利率，含Crowding评分和DTC | 机构级定价（需联系） | ★★★★★ | 对冲基金级别 |
| **SpotGamma** | GEX分析行业第一，含Gamma翻转点、SIV波动率指数、TRACE工具 | 订阅制(需查询当前价) | ★★★★★ | Gamma团队首选 |
| **SentimenTrader** | 20,000+专有情绪指标，覆盖所有资产类别，含Optix情绪指数 | API起步价较高 | ★★★★★ | 情绪量化团队专业级 |
| **Bloomberg Terminal** | 全方位金融数据，含期权、空仓、新闻、分析师预期 | ~$25,000/年 | ★★★★★ | 全团队通用但成本极高 |

### 🥈 Tier 2：专业零售级数据（性价比最优，推荐起步）

| 平台 | 核心优势 | 价格 | 准确度 | 适合谁 |
|------|----------|------|--------|--------|
| **Unusual Whales** | 期权异常活动检测最佳性价比。含Flow Feed、0DTE Flow、暗池追踪、国会议员交易追踪、GEX图表 | $50/月(Entry), $44/月(年付) | ★★★★ | Gamma团队+期权流 |
| **Fintel** | 空仓数据(NASDAQ/NYSE官方源) + 暗池Off-Exchange数据(FINRA) + 13F/13D持仓追踪 + 自研挤压评分模型 | 免费基础版, 付费版分级 | ★★★★ | 空仓+持仓分析 |
| **FlowAlgo** | 期权大单检测最强，含暗池prints、语音提醒 | $149/月(月付), $99/月(年付) | ★★★★☆ | 日内交易+Gamma团队 |
| **Barchart** | 免费GEX图表（SPY/SPX等）+ 期权链 + 异常活动筛选。入门学习最佳 | 免费基础版, Premier $29.95/月 | ★★★★ | 全团队入门级 |
| **ChartMill** | 专业低流通股/空仓筛选器，含Short Squeeze Trading Ideas预设 | 免费+付费 | ★★★★ | 突破团队+空仓团队 |
| **Stock Rover** | 深度基本面筛选+空仓数据+自定义Screener，可编程 | $7.99-$27.99/月 | ★★★★ | 动量+基本面团队 |

### 🥉 Tier 3：免费/低成本数据源（数据入口+自建系统基础）

| 平台/API | 核心数据 | 价格 | 限制 | 适合场景 |
|----------|----------|------|------|----------|
| **Finviz** | 股票筛选器(Float, Short Float%, 技术指标)、热图、盘前异动 | 免费(延迟) / Elite $39.5/月(实时) | 免费版延迟15分钟 | 所有团队的日常筛选起点 |
| **Yahoo Finance (yfinance)** | Python免费获取历史价格、基本面、期权链 | 完全免费 | 无实时、偶尔数据不稳定 | 回测+历史分析 |
| **Alpha Vantage** | 实时行情+技术指标+新闻情绪API | 免费(5次/分钟) / $49.99/月 | 免费版调用次数极少 | API自建系统 |
| **Finnhub** | 实时行情+社交情绪+内部人交易+SEC Filing | 免费(60次/分钟) / 付费版更多 | 免费版够用于原型开发 | 情绪团队+全栈API |
| **Financial Modeling Prep** | 财务报表+技术指标+筛选器API | 免费(250次/天) / $14/月+ | 免费版限制较多 | 动量团队基本面数据 |
| **FINRA Short Interest** | 官方空仓数据（每月两次） | 免费 | 延迟2周 | 基准验证数据 |
| **ApeWisdom** | Reddit/4Chan股票提及频率追踪 | 免费 | 仅提及计数，无情绪分析 | 情绪团队快速扫描 |
| **Quiver Quantitative** | WSB提及+国会交易+政府合同+Reddit情绪 | 免费基础 / API付费 | 数据维度有限 | 情绪团队辅助 |
| **Google Trends** | 搜索热度指数 | 免费 | 日级粒度、相对值非绝对值 | 情绪异常检测 |
| **TradingView** | 图表+社区+技术分析+Pine Script回测 | 免费(有限) / Pro $14.95/月+ | 免费版广告多、指标限制 | 突破团队图表分析+回测 |

---

## 三、推荐技术栈（自建数据管道用）

如果你打算用Python自建分析系统，以下是核心库：

### 数据获取层

```
yfinance          — 免费历史行情+期权链+基本面（最常用，零成本起步）
finnhub-python    — 实时行情+社交情绪+内部人交易+Filing
alpha_vantage     — 技术指标+新闻情绪+行情API
praw              — Reddit API（直接爬取r/WSB等subreddit）
tweepy            — Twitter/X API（需申请开发者账号）
polygon-api-client— Polygon.io实时+历史行情（有免费层）
```

### NLP/情绪分析层

```
transformers (HuggingFace) — 加载FinBERT/RoBERTa-financial等金融NLP模型
vaderSentiment    — 基于规则的情绪分析（快速但精度一般，适合初筛）
TextBlob          — 简易情绪分析
spaCy             — NLP基础（分词、命名实体识别）
```

### 量化分析层

```
pandas / numpy    — 数据处理核心
TA-Lib / pandas_ta— 技术指标计算（RSI, MACD, ATR, OBV, VWAP...）
scipy.stats       — 统计检验（Granger因果检验等）
statsmodels       — 时间序列分析（GARCH, VAR等）
backtrader / zipline / QuantConnect — 回测框架
```

### 可视化层

```
plotly            — 交互式图表（K线图、GEX热图）
matplotlib        — 基础绘图
streamlit / dash  — 快速搭建Dashboard
```

---

## 四、数据准确性红线（关键注意事项）

### ⚠️ 空仓数据的"2周真空"问题

这是最关键的数据质量陷阱：

- **FINRA官方**数据每月只发布两次（月中+月末），有约2周延迟
- 这意味着你看到的"官方"Short Interest可能已经过时
- **解决方案**：用ORTEX/S3的**估算数据**（基于证券借贷数据推算），ORTEX声称其模型预测准确率达97%
- **交叉验证**：将ORTEX估算值与下一次FINRA官方数据对比，评估偏差

### ⚠️ 期权数据的OI延迟

- Open Interest在每日收盘后更新，非实时
- 盘中只能看到Volume（成交量），而非新建仓vs平仓
- **解决方案**：用"Volume vs OI对比"推断（当日Volume >> 前日OI = 大量新建仓）
- SpotGamma和TradingVolatility等平台正在开发盘中GEX估算模型

### ⚠️ 社交媒体数据的Bot污染

- Reddit和Twitter上存在大量Bot账号制造虚假情绪
- **解决方案**：
  - 过滤账号年龄<30天的帖子
  - 过滤Karma<100的Reddit用户
  - 检测异常发帖频率（>50帖/天大概率是Bot）
  - 用NLP检测模板化/重复性内容

### ⚠️ Float数据的不一致性

- 不同平台报告的Float数字可能差异很大（Finviz vs Yahoo vs Bloomberg）
- 原因：对"限售股"、"内部人持股"、"战略持股"的定义不同
- **解决方案**：以SEC Filing（10-K/10-Q）中的shares outstanding为基准，自行扣除已知的内部人/机构锁定股

### ⚠️ 回测中的生存者偏差

- 只回测"现在还在交易的股票"会高估策略成功率
- 退市/破产的股票在回测数据中被剔除了
- **解决方案**：使用包含退市股票的完整历史数据库（如CRSP、Sharadar）

---

## 五、分阶段实施路线图（从零到实战）

### Phase 1：零成本起步（$0/月）

**目标**：验证策略逻辑，建立数据直觉

| 用途 | 工具 | 成本 |
|------|------|------|
| 日常筛选 | Finviz（免费版） | $0 |
| 历史数据+回测 | yfinance + pandas + TA-Lib | $0 |
| 空仓基础 | Finviz Short Float筛选 + FINRA官方 | $0 |
| 情绪快速扫描 | ApeWisdom + Google Trends | $0 |
| 图表分析 | TradingView（免费版） | $0 |
| 期权链 | yfinance期权模块 | $0 |
| Reddit数据 | praw (Reddit API) | $0 |

**这个阶段做什么**：用免费数据搭建Python原型系统，跑通5个团队的基本筛选逻辑。不做实盘交易，只做纸面追踪(paper trading)验证。

---

### Phase 2：核心升级（~$100-200/月）

**目标**：补齐关键数据盲区，开始纸盘验证

| 用途 | 工具 | 成本 |
|------|------|------|
| 空仓数据（实时估算） | ORTEX Basic | $39/月 |
| 期权流+异常活动+GEX | Unusual Whales | ~$50/月 |
| 实时筛选+图表 | Finviz Elite 或 TradingView Pro | ~$15-40/月 |
| API数据源 | Finnhub 免费 + Alpha Vantage 免费 | $0 |

**这个阶段做什么**：每天运行筛选 → 生成候选名单 → 按团队流程评估 → 纸面追踪30-60天 → 统计实际成功率 → 迭代调整阈值。

---

### Phase 3：完整武装（~$300-500/月）

**目标**：全数据覆盖，具备实战能力

| 用途 | 工具 | 成本 |
|------|------|------|
| 空仓深度分析 | ORTEX Advanced | $129/月 |
| 期权流（专业级） | Unusual Whales 或 FlowAlgo | $50-149/月 |
| GEX专业分析 | SpotGamma 或 Barchart Premier | $30-100/月 |
| 情绪量化 | Finnhub付费 或 自建NLP系统 | $50+/月 或 GPU算力 |
| 全栈图表+回测 | TradingView Premium | ~$30/月 |
| 催化剂日历 | Earnings Whispers Premium | ~$10-30/月 |

---

## 六、一句话总结：每个团队的"最小可行数据集"

| 团队 | 绝对必须有 | 锦上添花 |
|------|-----------|----------|
| 🔴 空仓挤压 | ORTEX (空仓估算+借券费) + Finviz (筛选) | S3 Partners、暗池数据 |
| 🟠 Gamma挤压 | Unusual Whales (异常期权流) + Barchart (免费GEX) | SpotGamma、FlowAlgo |
| 🟡 社交情绪 | praw (Reddit API) + ApeWisdom + Google Trends | FinBERT模型、SentimenTrader |
| 🟢 低流通突破 | Finviz (Float筛选) + yfinance (行情) + 实时RVOL | MOMO App、TradingView实时 |
| 🔵 动量+催化 | yfinance (历史价格) + Earnings Whispers (日历) | Stock Rover(深度筛选)、Finnhub |

> **最终建议**：先从Phase 1的免费工具开始验证策略逻辑。只有当纸面追踪证明策略有效后，再逐步升级到付费数据源。数据订阅费就是你的"研发投入"——但前提是你已经证明了研发方向是对的。