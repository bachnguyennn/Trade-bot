# Research results

Produced on 2026-11-11 by `python -m src.cli pipeline run` on real data. Every number below
was computed by the code in this repository; none was edited. Re-running the pipeline on the
same stored data reproduces the event study and the backtests exactly.

**Read this first.** These results describe the past. They show association, not that any
post caused any price move. Nothing here is investment advice.

## Bottom line

- There is **no reliable evidence** that these posts are followed by abnormal next-day
  returns in the mapped symbols once dependence between events is accounted for.
- The baseline model shows **no demonstrated skill** over naive baselines.
- **No strategy beats buy-and-hold** SPY. Two of three lose money after costs.

## Data used

| Item | Value |
|------|-------|
| Posts | 29,409, from 2022-02-14 to 2025-10-25 (CC0 archive, frozen 2025-10-26) |
| Reposts and media-only posts excluded | 6,452 and 5,053 |
| Market-relevant posts | 1,540, merged into 1,371 events |
| Symbols | 76 US stocks and ETFs; benchmark SPY |
| Candles | 358,055, all labelled `delayed` (Yahoo Finance via yfinance) |
| Daily bars | 2021-12-01 to 2026-11-10 |
| Hourly bars | from 2024-11-12 only |
| 5, 15, 30-minute windows | **unavailable**: no bars that fine cover the event period |

## Event study

Mean abnormal return (symbol minus SPY) per event, in basis points.

| Window | Events | Mean | Naive t | Baseline-adjusted mean | Sessions | Session-clustered mean | Clustered t | p |
|--------|-------:|-----:|--------:|-----------------------:|---------:|-----------------------:|------------:|--:|
| 1 hour | 595 | +2.0 | 1.14 | n/a | 201 | +1.0 | 0.46 | 0.645 |
| 4 hours | 497 | -5.7 | -1.87 | n/a | 182 | -3.2 | -0.93 | 0.354 |
| Next trading day | 1,371 | -9.0 | **-4.08** | -7.5 | 561 | -4.1 | -1.48 | 0.140 |
| Close to close (not tradable) | 1,371 | -3.3 | -1.13 | -2.8 | 552 | -0.3 | -0.07 | 0.944 |

How to read it:

- The naive next-day t-statistic of -4.08 looks like a strong effect. It is not. Many events
  enter on the same session and share one market move, so they are not independent
  observations. Averaging events per session first gives t = -1.48 (p = 0.14).
- The baseline is the same symbols' average abnormal return on all sessions. It removes
  drift that has nothing to do with posts.
- The hourly windows cover only events from November 2024 onward.

Next trading day, by category (session-clustered, baseline-adjusted):

| Category | Events | Sessions | Mean (bps) | t | p |
|----------|-------:|---------:|-----------:|--:|--:|
| Banking and monetary policy | 297 | 232 | -3.4 | -0.80 | 0.424 |
| Defence | 154 | 126 | -12.2 | -1.80 | 0.075 |
| Energy and oil | 187 | 166 | -10.6 | -1.53 | 0.127 |
| Government spending | 252 | 191 | -5.9 | -1.46 | 0.146 |
| Immigration and employment | 78 | 65 | -45.7 | -2.41 | 0.019 |
| Sanctions and international | 396 | 287 | -1.7 | -0.40 | 0.688 |
| Tariffs and trade | 225 | 151 | -1.7 | -0.40 | 0.691 |
| Technology and semiconductors | 109 | 93 | +9.8 | 1.15 | 0.252 |

The immigration category is the only one below p = 0.05. It rests on 65 sessions and two
small, volatile symbols (GEO, CXW), and it is one of 32 category-window tests with no
multiple-comparison correction. One result at that level is expected by chance. Treat it as
a hypothesis to test on new data, not a finding.

## Baseline model

TF-IDF text features with logistic regression, predicting the sign of the next-day abnormal
return. Model version `20261111T163308Z-4dbf7dc5`.

| Split | Period | Samples | Events |
|-------|--------|--------:|-------:|
| Train | 2022-04-29 to 2025-04-08 | 4,578 | 954 |
| Validation | 2025-04-09 to 2025-06-26 | 1,011 | 196 |
| Test (held out) | 2025-06-29 to 2025-10-25 | 1,074 | 206 |

| Test-period measure | Model | Naive baseline |
|---------------------|------:|---------------:|
| Accuracy | 51.3% (95% CI 48.3% to 54.3%) | 54.4% always up; 50.0% coin flip; 45.6% majority class |
| Log loss | 0.6983 | 0.7012 constant rate |
| ROC AUC | 0.526 | 0.5 |
| Magnitude MAE | 73.9 bps | 71.8 bps predicting zero |
| Rank correlation | 0.036 | 0 |

Verdict recorded in the report: `beats_baseline = false`. The accuracy interval includes
coin-flip accuracy and sits below the always-up rate. Walk-forward accuracy over 4,189
samples is 52.9% (CI 51.4% to 54.4%), which is slightly above 50% but small, and the samples
are correlated, so the interval is too narrow.

The volatility head reaches ROC AUC 0.68. That mostly reflects knowing which symbols are
volatile, not understanding posts.

## Backtests

Costs 1 bp and slippage 2 bps per side, 3% stop-loss, 5% of equity per position, one position
per symbol, 60 s assumed collection latency plus 30 s decision latency, next-day holding
window. Short sales assumed available at no borrow cost.

| Strategy | Period | Trades | Return | SPY return | Sharpe | Max drawdown | Win rate | Profit factor |
|----------|--------|-------:|-------:|-----------:|-------:|-------------:|---------:|--------------:|
| A. Immediate reaction | 2024-07-10 to 2025-10-27 | 1,490 | +4.25% | +23.94% | 1.00 | -2.28% | 48.7% | 1.12 |
| B. Momentum continuation | 2022-05-03 to 2025-10-28 | 2,750 | -3.43% | +73.39% | -0.41 | -5.46% | 48.0% | 0.95 |
| C. Mean reversion | 2022-05-03 to 2025-10-28 | 724 | -3.03% | +73.39% | -0.55 | -4.23% | 47.0% | 0.88 |

- Strategy A is the only one with a positive result, and it earns far less than holding SPY.
  Its Sharpe ratio is close to SPY's (0.98) because it is rarely invested, not because it
  predicts well: its win rate is below 50% and the model behind it shows no demonstrated
  skill. One 15-month period is not enough to tell a small edge from luck.
- Strategy A covers a shorter period because it only trades on out-of-sample predictions.
- Strategies B and C lose money after costs. Neither continuation nor reversal of the first
  day's move is supported.

## Limits that apply to everything above

- Market data is delayed, not consolidated. Daily open and close prices from Yahoo can
  differ slightly from official prints.
- The symbol universe was chosen in 2026, so it leans toward names that still exist
  (survivorship bias).
- Events and their symbols come from keyword rules that have not been validated against
  human labels. Mis-mapped events dilute any real effect.
- Abnormal return has no beta adjustment.
- The assumed 60-second collection latency for historical posts is an assumption, not a
  measurement.
- Fills at the open assume no market impact and no borrow constraints.

## Reproduce

```bash
python -m src.cli pipeline run
python -m src.cli research event-study --full
```

Reports are written to `data/reports/`. The event-study report ID is a hash of its results,
so an identical ID means identical numbers.
