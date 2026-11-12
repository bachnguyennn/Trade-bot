# Labelling posts by hand

The keyword rules decide which posts count as market events and which stocks they affect.
Nobody has checked them. Hand labels do two things:

1. Measure the rules: how many posts they flag are really market-relevant (precision), how
   many relevant posts they miss (recall), and whether they pick the right symbols.
2. Define a narrow subset, posts that name a company or announce a concrete action, and test
   whether prices react to those more than to general commentary.

## Steps

```bash
python -m src.cli research label-sample          # writes data/labels/label_sheet.csv
# fill in the sheet (see below), save it as CSV in the same place
python -m src.cli research label-eval            # scores the rules, tests the subset
```

`label-sample` draws 200 posts the rules call relevant and 100 they reject, shuffled. The
sheet does not show which is which, or what the rules decided, so your labels are not
anchored on them. That information is kept in `label_sheet.meta.json` next to the sheet.

The command refuses to overwrite an existing sheet, so your labels are safe. `--force`
replaces it. `--relevant`, `--other`, and `--seed` change the sample.

You can label in any order and run `label-eval` at any time. Rows with an empty `relevant`
cell are skipped. Rows with invalid values are listed under `errors` and left out.

The sheet is in `data/`, which is not committed: it contains post text, which this project
does not redistribute.

## Columns to fill in

| Column | Values | Meaning |
|--------|--------|---------|
| `relevant` | `y` or `n` | Could this post plausibly move the price of a listed US stock, sector, or the market? |
| `specificity` | `company`, `action`, or `general` | Required when `relevant` is `y`. See below. |
| `symbols` | Tickers from the list below, separated by spaces | The stocks you would expect to move. Leave empty if none in the list fit. |
| `notes` | Free text | Optional. Useful for hard cases. |

Leave the `post_id`, `published_at_utc`, and `text` columns as they are. The `p` in front
of each ID stops spreadsheet programs from turning it into a rounded number.

### Specificity

- **company**: names a specific company, its product, or its chief executive, in a way that
  could affect that company. "Apple will build its phones in America or pay a 25% tariff."
- **action**: announces, threatens, or reports a concrete policy action with an identifiable
  target. A tariff rate, a sanction, an order, a deal, a nomination to the Fed. "Tariffs on
  Canadian steel go to 50% on Monday."
- **general**: market-related commentary with no concrete action. "The stock market is at
  record highs", "Interest rates are far too high".

When a post fits more than one, choose the most specific: `company` over `action` over
`general`.

### Relevant or not

Mark `y` when a reasonable trader could act on it. Campaign posts, personal attacks, media
complaints, and holiday greetings are `n` even when they mention the economy in passing.
Links with no text are `n` unless the link itself makes the subject obvious.

## Symbols

Only these symbols are measured. SPY is the benchmark, so it cannot be labelled.

| Sector | Symbols |
|--------|---------|
| Broad market | QQQ, IWM, DIA |
| Autos | GM, F, TSLA |
| Commodities | GLD |
| Consumer | NKE, WMT, TGT, HOG |
| Defence | ITA, LMT, RTX, NOC, GD |
| Energy | XLE, USO, XOM, CVX, COP, OXY, SLB, LNG |
| Financials | XLF, KRE, JPM, BAC, GS, WFC, COIN |
| Health care | XLV, UNH, PFE, LLY |
| Industrials | CAT, DE, BA, XLI, PAVE |
| International | FXI (China), KWEB (China internet), BABA, EWW (Mexico), EWC (Canada), EWJ (Japan), VGK (Europe), INDA (India), EWZ (Brazil), EWY (South Korea), EWT (Taiwan) |
| Materials | NUE, CLF, AA, FCX |
| Media | DJT, DIS, CMCSA |
| Rates | TLT |
| Private prisons | GEO, CXW |
| Technology | XLK, SMH, NVDA, AMD, INTC, TSM, MU, AVGO, AAPL, MSFT, GOOGL, META, AMZN, PLTR |

Prefer the most direct symbol. A tariff on Mexican goods is EWW; a post about steel tariffs
is NUE, CLF, and perhaps AA; a post naming Lockheed is LMT. Use a sector fund (XLE, SMH)
only when no single company is the clear target.

## What `label-eval` reports

- **relevance**: precision of the rules, the share of rejected posts that were in fact
  relevant, and an estimate of recall weighted by how many posts each group represents.
- **symbols**: for posts both you and the rules call relevant, how many rule symbols you
  agreed with (precision) and how many of yours the rules found (recall).
- **reaction_specific** and **reaction_general**: the reaction-size test (see
  `docs/RESEARCH_RESULTS.md`) run on your `company` and `action` posts with your symbols,
  and separately on your `general` posts.

Only posts published during market hours are tested at intraday windows. About a third of
posts are, so 200 relevant posts give roughly 60 to 70 testable posts. If the specific
group shows a hint of a reaction, label more to confirm it before acting on it.
