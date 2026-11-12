# Research results

Produced on 2026-11-11 by `python -m src.cli pipeline run --skip-download` and
`python -m src.cli research reaction-size` on real data. Every number below was computed by
the code in this repository; none was edited. Re-running on the same stored data reproduces
each report exactly (identical report IDs).

**Read this first.** These results describe the past. They show association, not that any
post caused any price move. Nothing here is investment advice.

## Bottom line

- **No directional effect.** The average abnormal return after a post is indistinguishable
  from zero at every window from 5 minutes to the next trading day.
- **Slightly more trading, not bigger moves.** For posts made while the market is open,
  traded volume in the mapped symbols is 4% to 8% above normal for about an hour. Price
  moves are at most about 2 bps larger than normal, below the 6 bps round-trip cost assumed
  in the backtests.
- **The baseline model has no skill.** Held-out accuracy is 49.0%.
- **No strategy beats buy-and-hold SPY, and all three lose money** after costs.

If a tradable effect exists, it is concentrated in a small subset of posts and diluted by
the keyword mapping. See "What this points to" at the end.

## Data used

| Item | Value |
|------|-------|
| Posts | 38,017, from 2022-02-14 to 2026-11-11 |
| Post sources | `stiles` CC0 archive to 2025-10-25; `cnn` continuation after that (terms not verified, see `docs/DATA_SOURCES.md`) |
| Reposts and media-only posts excluded | 7,567 and 7,664 |
| Market-relevant posts | 2,517, merged into 2,191 events (classifier `rules-v1`) |
| Symbols | 76 US stocks and ETFs; benchmark SPY |
| Market data | Alpaca, consolidated (SIP) feed, labelled `consolidated` |
| Daily bars | 94,392, 2021-12-01 to 2026-11-11 |
| 5-minute bars | 7,083,386, 2022-02-01 to 2026-11-11, regular session only |

Post text is repaired for mis-decoded characters on import (about 1,400 posts were affected).

## Event study: direction

Event study `es_5687b55b640b`. Mean abnormal return (symbol minus SPY) per event, in basis
points. "Clustered" averages events within a trading session first, because events on the
same session share one market move and are not independent.

| Window | Events | Naive mean | Naive t | Sessions | Clustered mean | Clustered t | p | Share up |
|--------|-------:|-----------:|--------:|---------:|---------------:|------------:|--:|---------:|
| 5 minutes | 2,186 | -0.7 | -1.17 | 796 | -0.5 | -0.77 | 0.44 | 48.7% |
| 15 minutes | 2,171 | -1.1 | -1.31 | 795 | -0.4 | -0.46 | 0.65 | 49.5% |
| 30 minutes | 2,159 | -2.7 | -2.90 | 794 | -1.3 | -1.12 | 0.27 | 47.6% |
| 1 hour | 2,119 | -2.8 | -2.62 | 787 | -0.9 | -0.67 | 0.50 | 47.7% |
| 4 hours | 1,776 | -5.3 | -2.87 | 710 | -1.8 | -0.79 | 0.43 | 46.0% |
| Next trading day | 2,191 | -6.7 | -3.55 | 796 | -2.4 | -0.96 | 0.34 | 45.6% |
| Close to close (not tradable) | 2,191 | -4.1 | -1.64 | 796 | +0.0 | +0.01 | 0.99 | 47.5% |

- The naive t-statistics look significant and are not: they treat events that share a
  session as independent. Clustered by session, nothing is close to significant.
- Windows start at the first bar after the post plus 30 seconds of decision latency, or at
  the next open for posts made outside trading hours. A 4-hour window that would cross the
  close is reported as unavailable, which is why it has fewer events.
- By category (56 category-by-window tests), two fall below p = 0.05: energy at 30 minutes
  and government spending close to close. About three are expected by chance alone, so
  neither is a finding.

## Reaction size: do prices move more than usual?

Report `rs_fc73e16c322b`. The table above averages signed returns, so a rise after one post
and a fall after another cancel out. This test ignores direction. It compares each event's
absolute abnormal return, and its traded volume, with the same symbol over the same window
at the same time of day on the 10 sessions either side that had no event for that symbol.
Excess values are clustered by session.

Posts made while the market is open (about 400 sessions per window):

| Window | Move after post | Normal move | Clustered excess | p | Volume vs normal | p |
|--------|----------------:|------------:|-----------------:|--:|-----------------:|--:|
| 5 minutes | 9.3 bps | 8.7 bps | +0.3 bps | 0.45 | +8.1% | 0.0002 |
| 15 minutes | 15.4 bps | 14.5 bps | +1.1 bps | 0.08 | +6.4% | 0.0005 |
| 30 minutes | 21.5 bps | 19.9 bps | +1.7 bps | 0.04 | +3.6% | 0.04 |
| 1 hour | 29.3 bps | 27.6 bps | +2.2 bps | 0.05 | +4.1% | 0.02 |
| 4 hours | 58.1 bps | 56.1 bps | +0.8 bps | 0.73 | +3.9% | 0.08 |
| Next trading day | 90.6 bps | 88.3 bps | +1.8 bps | 0.54 | n/a | |

Posts made outside trading hours, measured from the next open (about 625 sessions): no
window shows a larger move than normal, and volume is 2% to 3% above normal. Any reaction to
these posts would be in the overnight gap, which these windows do not contain.

How to read it:

- The volume increase in the first 15 minutes is the most consistent effect found so far.
  The market notices the posts.
- The extra price movement is small. Even taken at face value, 1 to 2 bps is well below the
  costs a strategy would pay.
- Volume is compared with the geometric mean of the control sessions, because volume is
  right-skewed and an arithmetic mean would bias the ratio downward.
- 14,657 of 63,666 measurements had fewer than 5 usable control sessions and were left out.
- Control sessions can contain unrelated news, or posts about other symbols. Both push the
  result toward "no difference".

## Baseline model

TF-IDF text features with logistic regression, predicting the sign of the next-day abnormal
return. Model version `20261111T232154Z-f71642cc`.

| Split | Period | Samples | Events |
|-------|--------|--------:|-------:|
| Train | 2022-04-29 to 2026-01-16 | 7,573 | 1,523 |
| Validation | 2026-01-20 to 2026-06-15 | 1,716 | 329 |
| Test (held out) | 2026-06-15 to 2026-11-10 | 1,757 | 329 |

| Test-period measure | Model | Naive baseline |
|---------------------|------:|---------------:|
| Accuracy | 49.0% (95% CI 46.6% to 51.3%) | 50.6% majority class; 49.4% always up; 50.0% coin flip |
| Log loss | 0.7015 | 0.6939 constant rate |
| ROC AUC | 0.505 | 0.5 |
| Magnitude MAE | 99 bps | 97 bps predicting zero |
| Rank correlation | -0.025 | 0 |

Verdict recorded in the report: `beats_baseline = false`. Walk-forward accuracy over 6,967
samples is 52.6%, but the samples are correlated, so its interval is too narrow to rely on.

The volatility head reaches ROC AUC 0.71. That mostly reflects knowing which symbols are
volatile, not understanding posts.

## Backtests

Costs 1 bp and slippage 2 bps per side, 3% stop-loss, 5% of equity per position, one position
per symbol, 60 s assumed collection latency plus 30 s decision latency, next-day holding
window. Short sales assumed available at no borrow cost.

| Strategy | Period | Trades | Return | SPY return | SPY Sharpe | Sharpe | Max drawdown | Win rate | Profit factor |
|----------|--------|-------:|-------:|-----------:|-----------:|-------:|-------------:|---------:|--------------:|
| A. Immediate reaction | 2025-03-03 to 2026-11-11 | 2,147 | -5.26% | +32.72% | 1.05 | -0.95 | -7.60% | 47.0% | 0.91 |
| B. Momentum continuation | 2022-05-03 to 2026-11-11 | 4,364 | -9.54% | +93.83% | 0.95 | -0.81 | -10.88% | 47.9% | 0.92 |
| C. Mean reversion | 2022-05-03 to 2026-11-11 | 1,314 | -9.04% | +93.83% | 0.95 | -1.13 | -9.13% | 45.7% | 0.80 |

- Strategy A was the only profitable one on data to October 2025 (+4.0%). With another year
  of posts it loses money, consistent with the earlier gain being luck.
- Strategy A covers a shorter period because it only trades on out-of-sample predictions.
- Neither continuation nor reversal of the first day's move is supported.

## Limits that apply to everything above

- The symbol universe was chosen in 2026, so it leans toward names that still exist
  (survivorship bias).
- Events and their symbols come from keyword rules that have not been validated against
  human labels. Mis-mapped events dilute any real effect.
- Abnormal return has no beta or sector adjustment.
- The assumed 60-second collection latency for historical posts is an assumption, not a
  measurement.
- Posts after 2025-10-25 come from a source whose reuse terms were not verified.
- Fills at the open assume no market impact and no borrow constraints.

## What this points to

The broad version of the idea, that a keyword-matched post moves the mapped stocks in a
predictable direction, is not supported at any horizon tested. The volume result says the
market reacts to something, so the remaining question is whether a narrow, well-defined
subset of posts (for example those naming a specific company or announcing a concrete
action) produces moves large enough to trade. That needs hand-labelled posts; see
`docs/ROADMAP.md`.

## Reproduce

```bash
python -m src.cli ingest posts --source stiles
python -m src.cli ingest posts --source cnn        # requires TRADEBOT_ALLOW_UNVERIFIED_SOURCES=true
python -m src.cli ingest market --interval 1d --start 2021-12-01
python -m src.cli ingest market --interval 5m --start 2022-02-01   # needs Alpaca keys
python -m src.cli pipeline run --skip-download
python -m src.cli research reaction-size
```

Reports are written to `data/reports/`. Report IDs are hashes of the results, so an
identical ID means identical numbers.
