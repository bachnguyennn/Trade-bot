# Security

## Secrets

- All credentials are read from `TRADEBOT_*` environment variables or a local `.env` file.
- `.env` and `.env.*` are ignored by Git; `.env.example` holds names only, with empty values.
- API keys are held as `SecretStr` and are not written to logs, reports, or API responses.
- `data/` (posts, candles, models, order state) is ignored by Git.
- A test (`test_no_secret_files_are_tracked`) fails if `.env`, any file under `data/`, or a
  Parquet, SQLite, or model file is tracked, or if `.env.example` contains a key value.

If a key is ever committed, revoke it at the provider first, then remove it from history.

## Paper trading boundary

| Control | Where |
|---------|-------|
| Only two brokers exist: simulator and Alpaca paper | `src/trading/broker.py`, `src/trading/alpaca_paper.py` |
| The paper adapter rejects every URL except `https://paper-api.alpaca.markets` | `AlpacaPaperBroker.__init__` |
| No setting holds a trading URL or a live flag | `src/core/settings.py`; asserted by a test |
| No source file names Alpaca's live host | asserted by `test_only_paper_and_data_hosts_appear_in_source` |
| No API route accepts a broker URL | asserted by `test_no_endpoint_accepts_a_broker_url` |
| Kill switch, daily loss limit, market-hours check, duplicate prevention | `src/trading/service.py` |

Use **paper** API keys only. A live Alpaca key would be rejected by the paper endpoint, but
it should never be placed in this project's environment.

## Input validation

- Every request body and query parameter is validated by Pydantic; unknown fields in
  contracts are rejected.
- List sizes are capped (`limit` at most 500; candles at most 5,000).
- Backtest IDs containing path separators or `..` are refused; report files are only read
  from the reports directory.
- Search text is matched literally, not as a regular expression.
- Archive payloads must be a JSON array of objects. Post HTML is reduced to plain text before
  storage; the dashboard renders text, never HTML.

## Network exposure

- The API binds to `127.0.0.1` by default, and Compose publishes ports on `127.0.0.1` only.
- **There is no authentication.** The platform is designed for one person on one machine.
  Do not expose the API to a network: anyone who can reach it can run pipelines, place paper
  orders, and change the kill switch. Put an authenticating reverse proxy in front before
  any shared use.
- CORS allows only the local dashboard origins.

## Outbound requests

| Destination | Purpose | Notes |
|-------------|---------|-------|
| `stilesdata.com` | Post archive | Plain GET with a generic user agent |
| `ix.cnn.io` | Optional archive continuation | Only when explicitly enabled |
| Yahoo Finance | Market data without keys | Through `yfinance` |
| `data.alpaca.markets` | Market data with keys | Keys sent as headers |
| `paper-api.alpaca.markets` | Paper orders, when selected | Keys sent as headers |

Requests back off on errors and honour `Retry-After`. Responses of 401, 403, and 404 are
final: an access restriction is never retried or worked around.

## Least privilege

- The API container runs as an unprivileged user and writes only to its data volume.
- CI has read-only repository permissions and uses no secrets.
- The default test run needs no network access and no credentials.

## Dependencies

Runtime dependencies are listed in `pyproject.toml` and `frontend/package.json`, with a lock
file for the frontend. Review `pip list --outdated` and `npm audit` periodically. Model files
are loaded with `joblib`, which can execute code: load only models this installation trained.

## Reporting

This is a personal research project. Report a problem by opening an issue on the repository,
without including any credential or personal data.
