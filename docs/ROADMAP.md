# Roadmap

Status as of 2026-11-11. "Done" means implemented and covered by passing tests.

## Phase 1: Architecture and foundation — done

| Criterion | Status |
|-----------|--------|
| Repository structure established | Done |
| Architecture documented | Done |
| Shared models defined | Done: eight contracts, validated |
| Local environment starts | Done: API and dashboard run locally |
| CI runs | Done: backend, frontend, and Compose validation pass on GitHub Actions |
| Initial tests pass | Done |

## Phase 2: Historical research MVP — done

| Criterion | Status |
|-----------|--------|
| A real historical post is matched to market data | Done: 1,371 events, 6,742 next-day measurements |
| An event study can be reproduced | Done: identical report hash on re-run |
| A baseline model produces out-of-sample predictions | Done: 4,189 walk-forward predictions |
| The dashboard shows real research data | Built, type-checked, tested against the API contract, and served with real data. Not yet looked at in a browser |

## Phase 3: Deep learning and strategy development — partly done

| Item | Status |
|------|--------|
| Baseline model evaluated on a chronological holdout | Done |
| Three strategies with costs, slippage, stops, exposure limits | Done |
| Benchmark comparison | Done: buy-and-hold SPY |
| Reproducibility and leakage guards | Done: `tests/integration/test_research_integrity.py` |
| Transformer-based models (FinBERT embeddings, fine-tuning) | **Not started** |
| Gradient-boosted model on embeddings | **Not started** |
| Experiment comparison view in the dashboard | **Not started** |

The baseline shows no demonstrated skill and the event study shows no reliable effect, so
heavier models should follow better inputs, not precede them. See "Next" below.

## Phase 4: Real-time paper trading — built, awaiting a permitted live feed

| Criterion | Status |
|-----------|--------|
| New posts trigger an event-processing workflow | Done: `run_live_cycle`, tested end to end on synthetic posts |
| Eligible events produce model predictions | Done |
| Trading rules can emit a no-trade signal | Done |
| Valid signals can submit paper orders | Done with the simulator. The Alpaca paper adapter is tested against a mock only |
| Orders and portfolio state reconcile | Done |
| A kill switch stops new orders | Done |
| A permitted source of new posts | **Open.** The only identified source has unverified terms and is off by default |
| Scheduled polling | **Not started.** A cycle runs on request (`POST /api/v1/ingest/run`) |

## Next, in priority order

1. **Decide on a source of new posts.** Review the terms of the hosted archive continuation,
   or license a feed. Without this, nothing after October 2025 can be studied or paper traded.
2. **Get intraday history.** Add Alpaca keys and backfill 5-minute bars to 2022. The research
   question is about minutes and hours, and today only next-day windows cover the full period.
3. **Label a sample of posts by hand** (a few hundred) to measure the classifier's precision
   and recall and to train a relevance model. The rules are currently unvalidated.
4. **Run the Alpaca paper adapter against a real paper account** and reconcile.
5. **Better abnormal returns**: market-model beta, sector-relative returns.
6. **Period-matched placebo test**: compare event days with matched non-event days instead
   of a full-period baseline, and correct for multiple comparisons.
7. **Transformer embeddings** as model inputs, compared with the TF-IDF baseline on the same
   splits. Only worth doing once items 2 and 3 are in place.
8. **Scheduler** for live cycles, with alerts when the source is stale.
9. **Historical universe membership** to reduce survivorship bias.
10. **Authentication** if the API is ever used by more than one person.

## Known limitations

- Market data without keys is delayed and has short intraday history.
- The universe is curated today; delisted names are mostly absent.
- No borrow costs, market impact, or partial fills in backtests.
- The simulator fills at the last stored close, not a live quote.
- Docker files are provided and the Compose file is validated in CI, but the images were
  not built or run: the development machine has no Docker.
