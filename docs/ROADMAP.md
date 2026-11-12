# Roadmap

Status as of 2026-11-12. "Done" means implemented and covered by passing tests.

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
| A real historical post is matched to market data | Done: 2,191 events, measured from 5 minutes to the next day |
| An event study can be reproduced | Done: identical report hash on re-run |
| A baseline model produces out-of-sample predictions | Done: 6,967 walk-forward predictions |
| The dashboard shows real research data | Done: all six sections checked in a browser with real data, no console errors |

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

No effect has been found at any horizon from 5 minutes to the next day, and the baseline
has no skill (see `docs/RESEARCH_RESULTS.md`). Heavier models should follow better inputs,
not precede them.

## Phase 4: Real-time paper trading — built, awaiting a permitted live feed

| Criterion | Status |
|-----------|--------|
| New posts trigger an event-processing workflow | Done: `run_live_cycle`, tested end to end on synthetic posts |
| Eligible events produce model predictions | Done |
| Trading rules can emit a no-trade signal | Done |
| Valid signals can submit paper orders | Done with the simulator. The Alpaca paper adapter is tested against a mock only; keys are now available |
| Orders and portfolio state reconcile | Done |
| A kill switch stops new orders | Done |
| A source of new posts | Enabled locally: the `cnn` continuation, by the owner's decision. Its reuse terms are still unverified |
| Scheduled polling | **Not started.** A cycle runs on request (`POST /api/v1/ingest/run`) |

## Done since the first run

- Alpaca keys added; 5-minute consolidated bars backfilled from 2022-02 (7.1 million bars).
- Posts after October 2025 imported from the `cnn` continuation (38,017 posts in total).
- Mis-decoded characters in post text repaired.
- Reaction-size test (`research reaction-size`): posts during market hours are followed by
  4% to 8% higher volume for about an hour, but price moves only 1 to 2 bps larger than
  normal, below trading costs.

## Next, in priority order

1. **Label a sample of posts by hand** (a few hundred): is it market-relevant, which
   symbols, how specific (names a company, announces a concrete action, or general
   commentary). This measures the classifier and defines the narrow subset to test.
2. **Re-run the event study and reaction-size test on the specific subset.** This is the
   remaining test that could change the conclusion.
3. **Better abnormal returns**: market-model beta, sector-relative returns.
4. **Run the Alpaca paper adapter against a real paper account** and reconcile.
5. **Transformer embeddings** as model inputs, compared with the TF-IDF baseline on the same
   splits. Only worth doing if step 2 finds an effect.
6. **Scheduler** for live cycles, with alerts when the source is stale.
7. **Historical universe membership** to reduce survivorship bias.
8. **Review the `cnn` source's terms** before any use beyond personal research.
9. **Authentication** if the API is ever used by more than one person.

## Known limitations

- Market data without keys is delayed and has short intraday history (Alpaca keys fix this).
- The universe is curated today; delisted names are mostly absent.
- No borrow costs, market impact, or partial fills in backtests.
- The simulator fills at the last stored close, not a live quote.
- Docker files are provided and the Compose file is validated in CI, but the images were
  not built or run: the development machine has no Docker.
