# Social Sentiment Quant Memory

## Code Bridge
- Python: `src/teams/yellow/screener.py` -> `SocialSentimentScreener`
- Config: `config/default.yaml` -> `yellow_team`
- Scoring: mention_frequency, sentiment_polarity, sentiment_momentum, signal_quality (each 0-25)
- Run: `python main.py --teams yellow`

## Critical Bug: sentiment_polarity Always Zero
- Root cause: No Reddit API credentials (config/secrets.yaml does not exist)
- ApeWisdom API only returns mention counts/rank/upvotes, NOT post text
- VADER analyzer has no text to process -> avg_sentiment, bullish_pct, bearish_pct all default to 0.0
- This disables 25% of the scoring system (sentiment_polarity dimension = 0/25 for all tickers)
- Fix: create config/secrets.yaml with reddit_client_id + reddit_client_secret
- See `/root/Pi/SAnalysis/src/teams/yellow/screener.py` lines 266-283

## ApeWisdom Data Structure
- Cached with hash-based filenames: `apewisdom_{sha256[:16]}.json`
- Provides: mentions, rank, upvotes, mentions_24h_ago
- Key insight: mentions_24h_ago enables 24h growth rate calculation (useful for spike detection)
- 135x growth for IBM (2 -> 270) on 2026-02-24 was a genuine anomaly

## Signal Quality Assessment (as of 2026-02-24)
- signal_quality scores are inflated: source diversity + sample size give 11-14 pts even with zero sentiment data
- Google Trends provides cross-validation but is NOT an independent social media platform
- ApeWisdom = Reddit/4chan aggregate, so ApeWisdom + GT = effectively 1.5 independent sources, not 2

## Missing Capabilities
- No Twitter/X data source implemented
- No StockTwits data source implemented
- No Granger causality test implemented
- No bot/spam filtering active (requires Reddit API access)
- No historical baseline for anomaly detection (no sigma calculation for mention spikes)

## Key Patterns Observed
- HIMS showed Reddit-GT divergence (7.5x Reddit growth but GT=18) = concentrated community signal
- IBM showed all-dimensions spike (mentions + upvotes + GT) = likely real catalyst event
- Large-cap stocks (NVDA, MSFT, TSLA) maintain high baseline discussion = need higher anomaly thresholds
