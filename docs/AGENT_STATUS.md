# Agent status

Updated 2026-11-11. The work was carried out in a single session, phase by phase, with each
area kept to its own directories and integrated through the shared contracts.

## Summary

| Check | Result |
|-------|--------|
| Backend tests (`pytest`, offline) | 266 passed |
| Lint and format (`ruff`) | Clean |
| Types (`mypy src`) | Clean, 64 files |
| Frontend type check, tests, build | Clean; 15 tests passed |
| Real-data pipeline | Ran end to end; see `docs/RESEARCH_RESULTS.md` |

## By area

### A0 — Architecture

- **Owns**: `src/contracts`, `src/core`, `docs/`
- **Done**: eight contracts with validation; settings; time rules; storage; constitution,
  specification, plan, and tasks; architecture, contracts, decisions, roadmap.
- **Blockers**: none.
- **Next**: decide the source of new posts (roadmap item 1).

### A1 — Data engineering

- **Owns**: `src/ingestion`, `src/pipelines`
- **Done**: archive sources with retries and backoff; Bronze, Silver, and Gold builds;
  deduplication, edit versions, deletion marking, rejection report; incremental and live
  modes; live cycle.
- **Real data**: 29,409 posts imported; second import adds zero.
- **Blockers**: no verified source of posts after 2025-10-26.
- **Next**: scheduler for live cycles once a source is chosen.

### A2 — Market data

- **Owns**: `src/market_data`
- **Done**: Alpaca and yfinance providers with quality labels; NYSE calendar; 76-symbol
  universe with eligibility dates; candle store; event windows.
- **Real data**: 358,055 candles (daily from 2021-12, hourly from 2024-11), labelled `delayed`.
- **Not verified**: the Alpaca provider against the real service (no keys available);
  it is tested with a mock transport.
- **Next**: backfill 5-minute bars with Alpaca keys.

### A3 — ML

- **Owns**: `src/ml`
- **Done**: rule-based classifier and entity recognition; chronological purged splits and a
  leakage guard; TF-IDF baseline with three heads; walk-forward predictions; model registry;
  inference with version checks.
- **Real data**: test accuracy 51.3% (CI 48.3% to 54.3%); no demonstrated skill.
- **Not done**: transformer models; hand-labelled evaluation of the classifier.
- **Next**: label a sample of posts.

### A4 — Quantitative research

- **Owns**: `src/strategies`, `src/backtesting`
- **Done**: event study with baseline and session clustering; three strategies; event-driven
  engine with costs, slippage, stops, and limits; metrics; benchmark; reproducible runs.
- **Real data**: no strategy beats buy-and-hold; B and C lose money after costs.
- **Review notes**: the naive next-day statistic was misleading until session clustering
  was added (decision D-008).
- **Next**: period-matched placebo test; beta-adjusted returns.

### A5 — Backend and trading

- **Owns**: `src/api`, `src/trading`
- **Done**: 25 REST paths and a WebSocket stream; simulator; paper-only Alpaca adapter;
  order service with kill switch, loss limit, hours check, duplicate prevention, retries,
  and reconciliation; state that survives restarts.
- **Not verified**: the Alpaca paper adapter against a real paper account.
- **Next**: run it against a paper account.

### A6 — Frontend

- **Owns**: `frontend/`
- **Done**: six sections; typed client; empty, error, and loading states; data-quality
  badges; live-stream indicator.
- **Verified**: type check, production build, 15 component tests, and requests through the
  dev proxy to the running API with real data.
- **Not verified**: visual appearance in a browser (the browser automation could not reach
  the local server from where it runs).
- **Next**: experiment comparison view.

### A7 — QA, security, MLOps

- **Owns**: `tests/`, `.github/workflows/`, `infra/`
- **Done**: unit, integration, and contract tests; research-integrity guards; CI workflow;
  Dockerfiles and Compose; security notes.
- **Not verified**: the CI workflow has not run yet (it runs on GitHub after a push);
  Docker was not available locally.
- **Next**: confirm the first CI run is green.

## Quickstart scenarios

| Scenario | Outcome |
|----------|---------|
| 1. Offline checks | Passed |
| 2. Idempotent import | Passed on real data: second run reports 0 new posts |
| 3. Event study on real data | Passed: identical report hash on re-run |
| 4. Baseline model and backtests | Passed: reports written with splits, baselines, and assumptions |
| 5. API and dashboard | API verified with real data; dashboard built and served, not viewed in a browser |
| 6. Paper-trading safety | Passed |

## Environment notes

- The development machine has Python 3.12 but no Node.js and no Docker. The frontend was
  built with a portable Node.js 20 kept outside the repository.
- No Alpaca keys were available, so market data came from the keyless fallback.
