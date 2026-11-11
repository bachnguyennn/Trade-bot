import { api } from "../api/client";
import { AsyncView, Card, DataQualityBadge, Pill, StatCard, Table } from "../components/ui";
import { fmtInt, fmtMoney, fmtNum, fmtPct, fmtTime, label, signClass } from "../format";
import { useApi } from "../hooks";

export function Overview({ refreshKey }: { refreshKey: number }) {
  const [status, reloadStatus] = useApi(api.status, [refreshKey]);
  const [posts, reloadPosts] = useApi(() => api.posts({ limit: 5 }), [refreshKey]);
  const [signals, reloadSignals] = useApi(
    () => api.signals({ limit: 8, trades_only: true }),
    [refreshKey],
  );
  const [portfolio, reloadPortfolio] = useApi(api.portfolio, [refreshKey]);
  const [backtests, reloadBacktests] = useApi(api.backtests, [refreshKey]);

  return (
    <div className="space-y-4">
      <Card title="System status">
        <AsyncView
          result={status}
          reload={reloadStatus}
          emptyTitle="No status available"
          isEmpty={() => false}
        >
          {(s) => (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard
                label="Posts collected"
                value={s.posts > 0 ? fmtInt(s.posts) : "None"}
                note={s.latest_post_at ? `Latest ${fmtTime(s.latest_post_at)}` : "Run ingestion"}
              />
              <StatCard
                label="Market events"
                value={s.events > 0 ? fmtInt(s.events) : "None"}
                note={`${fmtInt(s.features)} window measurements`}
              />
              <StatCard
                label="Candles stored"
                value={s.candles > 0 ? fmtInt(s.candles) : "None"}
                note={`Provider: ${s.market_data_provider}`}
              />
              <div className="card p-4">
                <p className="card-title">Controls</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <DataQualityBadge quality={s.market_data_quality} />
                  <Pill tone={s.market_open ? "gain" : "muted"}>
                    Market {s.market_open ? "open" : "closed"}
                  </Pill>
                  <Pill tone={s.kill_switch ? "loss" : "gain"}>
                    Kill switch {s.kill_switch ? "ON" : "off"}
                  </Pill>
                  <Pill tone="accent">Broker: {s.broker}</Pill>
                  <Pill>{s.model_version ? `Model ${s.model_version}` : "No model trained"}</Pill>
                </div>
              </div>
            </div>
          )}
        </AsyncView>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Simulated account">
          <AsyncView
            result={portfolio}
            reload={reloadPortfolio}
            emptyTitle="No account data"
            isEmpty={() => false}
          >
            {(p) => (
              <div className="grid grid-cols-3 gap-3">
                <StatCard label="Account value" value={fmtMoney(p.equity)} note="Paper money" />
                <StatCard label="Day P&L" value={fmtMoney(p.day_pnl)} tone={signClass(p.day_pnl)} />
                <StatCard label="Gross exposure" value={fmtPct(p.gross_exposure, 1)} />
              </div>
            )}
          </AsyncView>
        </Card>

        <Card title="Strategy performance (backtests)">
          <AsyncView
            result={backtests}
            reload={reloadBacktests}
            emptyTitle="No backtests have been run"
            emptyHint="Run `tradebot backtest run --strategy ...` or use Strategy Research."
          >
            {(rows) => (
              <Table head={["Strategy", "Return", "Benchmark", "Sharpe", "Max DD", "Trades"]}>
                {rows.slice(0, 6).map((b) => (
                  <tr key={b.run_id}>
                    <td className="table-cell capitalize">{label(b.strategy)}</td>
                    <td className={`table-cell num ${signClass(b.metrics.cumulative_return)}`}>
                      {fmtPct(b.metrics.cumulative_return)}
                    </td>
                    <td className="table-cell num">
                      {fmtPct(b.benchmark_metrics?.cumulative_return)}
                    </td>
                    <td className="table-cell num">{fmtNum(b.metrics.sharpe_ratio)}</td>
                    <td className="table-cell num">{fmtPct(b.metrics.max_drawdown)}</td>
                    <td className="table-cell num">{fmtInt(b.metrics.trade_count)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </AsyncView>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Latest posts">
          <AsyncView
            result={posts}
            reload={reloadPosts}
            emptyTitle="No posts collected yet"
            emptyHint="Run `tradebot ingest posts` to import the archive."
          >
            {(rows) => (
              <ul className="space-y-3">
                {rows.map((post) => (
                  <li key={post.post_id} className="border-b border-surface-border/60 pb-3 last:border-0">
                    <p className="text-xs text-ink-faint">{fmtTime(post.published_at)}</p>
                    <p className="mt-1 line-clamp-3 text-sm">
                      {post.text || <span className="text-ink-faint">(media only)</span>}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </AsyncView>
        </Card>

        <Card title="Active signals">
          <AsyncView
            result={signals}
            reload={reloadSignals}
            emptyTitle="No trade signals"
            emptyHint="Signals appear after a backtest or a live ingestion run."
          >
            {(rows) => (
              <Table head={["Time", "Symbol", "Action", "Strategy"]}>
                {rows.map((s) => (
                  <tr key={s.signal_id} title={s.reason}>
                    <td className="table-cell text-ink-muted">{fmtTime(s.generated_at)}</td>
                    <td className="table-cell num font-semibold">{s.symbol}</td>
                    <td className={`table-cell uppercase ${s.action === "buy" ? "text-gain" : "text-loss"}`}>
                      {s.action}
                    </td>
                    <td className="table-cell capitalize text-ink-muted">{label(s.strategy)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </AsyncView>
        </Card>
      </div>
    </div>
  );
}
