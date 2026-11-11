import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type {
  BacktestMetrics,
  BacktestResult,
  EquityPoint,
  EventStudyReport,
  StrategyName,
  WindowStats,
} from "../api/types";
import { AsyncView, Card, DataQualityBadge, Pill, Table } from "../components/ui";
import { fmtBps, fmtDate, fmtInt, fmtNum, fmtPct, label, signClass } from "../format";
import { useApi } from "../hooks";

const STRATEGIES: StrategyName[] = [
  "immediate_reaction",
  "momentum_continuation",
  "mean_reversion",
];

function StudyTable({ rows }: { rows: WindowStats[] }) {
  return (
    <Table
      head={[
        "Window",
        "Events",
        "Mean abnormal",
        "Baseline",
        "Excess",
        "Sessions",
        "Clustered t",
        "Clustered p",
        "Share up",
      ]}
    >
      {rows.map((w) => (
        <tr key={w.window}>
          <td className="table-cell">
            {label(w.window)}
            {!w.tradable && <span className="ml-2 text-xs text-ink-faint">(not tradable)</span>}
          </td>
          <td className="table-cell num">{w.n_events > 0 ? fmtInt(w.n_events) : "—"}</td>
          <td className={`table-cell num ${signClass(w.mean_abnormal_ret)}`}>
            {fmtBps(w.mean_abnormal_ret)}
          </td>
          <td className="table-cell num">{fmtBps(w.baseline_mean_abnormal_ret)}</td>
          <td className={`table-cell num ${signClass(w.excess_mean_abnormal_ret)}`}>
            {fmtBps(w.excess_mean_abnormal_ret)}
          </td>
          <td className="table-cell num">{fmtInt(w.n_sessions)}</td>
          <td className="table-cell num">{fmtNum(w.session_clustered_t_stat)}</td>
          <td className="table-cell num">{fmtNum(w.session_clustered_p_value, 3)}</td>
          <td className="table-cell num">{fmtPct(w.share_positive, 1)}</td>
        </tr>
      ))}
    </Table>
  );
}

function EventStudy({ report }: { report: EventStudyReport }) {
  const [category, setCategory] = useState("");
  const rows = category ? (report.by_category[category] ?? []) : report.overall;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-faint">
        <DataQualityBadge quality={report.data_quality} />
        <span>
          {fmtInt(report.events_measured)} of {fmtInt(report.events_total)} events measured ·{" "}
          {fmtDate(report.period_start)} to {fmtDate(report.period_end)} · benchmark{" "}
          {report.benchmark_symbol} · report {report.report_id}
        </span>
        <select
          aria-label="Event study category"
          className="input"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {Object.keys(report.by_category).map((c) => (
            <option key={c} value={c}>
              {label(c)}
            </option>
          ))}
        </select>
      </div>
      <StudyTable rows={rows} />
      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer">How to read this, and its limits</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {report.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function drawdown(curve: EquityPoint[]): { t: number; dd: number }[] {
  let peak = -Infinity;
  return curve.map((p) => {
    peak = Math.max(peak, p.equity);
    return { t: new Date(p.ts).getTime(), dd: peak > 0 ? (p.equity / peak - 1) * 100 : 0 };
  });
}

function MetricRows({ name, m }: { name: string; m: BacktestMetrics | null }) {
  return (
    <tr>
      <td className="table-cell font-medium">{name}</td>
      <td className={`table-cell num ${signClass(m?.cumulative_return)}`}>
        {fmtPct(m?.cumulative_return)}
      </td>
      <td className="table-cell num">{fmtNum(m?.sharpe_ratio)}</td>
      <td className="table-cell num">{fmtNum(m?.sortino_ratio)}</td>
      <td className="table-cell num">{fmtPct(m?.max_drawdown)}</td>
      <td className="table-cell num">{fmtPct(m?.win_rate, 1)}</td>
      <td className="table-cell num">{fmtNum(m?.profit_factor)}</td>
      <td className="table-cell num">{m ? `${fmtNum(m.turnover, 1)}x` : "—"}</td>
      <td className="table-cell num">{m ? fmtInt(m.trade_count) : "—"}</td>
    </tr>
  );
}

function BacktestDetail({ result }: { result: BacktestResult }) {
  const curve = useMemo(() => {
    const bench = result.benchmark_curve.map((p) => ({
      t: new Date(p.ts).getTime(),
      benchmark: p.equity,
    }));
    const strategy = result.equity_curve.map((p) => ({
      t: new Date(p.ts).getTime(),
      strategy: p.equity,
    }));
    return [...bench, ...strategy].sort((a, b) => a.t - b.t);
  }, [result]);
  const dd = useMemo(() => drawdown(result.equity_curve), [result]);
  const tick = (t: number) => new Date(t).toISOString().slice(0, 7);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-faint">
        <DataQualityBadge quality={result.data_quality} />
        <span>
          {fmtDate(result.period_start)} to {fmtDate(result.period_end)} · run {result.run_id}
        </span>
        <Pill>{fmtInt(result.signal_count)} signals</Pill>
        <Pill>{fmtInt(result.no_trade_count)} not traded</Pill>
      </div>

      <Table
        head={["", "Return", "Sharpe", "Sortino", "Max drawdown", "Win rate", "Profit factor", "Turnover", "Trades"]}
      >
        <MetricRows name="Strategy (after costs)" m={result.metrics} />
        <MetricRows name={`Buy and hold ${result.benchmark_symbol}`} m={result.benchmark_metrics} />
      </Table>

      <div>
        <p className="card-title mb-2">Equity curve vs benchmark</p>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#263241" strokeDasharray="3 3" />
              <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                tickFormatter={tick} stroke="#5d6b7e" fontSize={11} />
              <YAxis domain={["auto", "auto"]} stroke="#5d6b7e" fontSize={11} width={72}
                tickFormatter={(v: number) => fmtInt(v)} />
              <Tooltip
                contentStyle={{ background: "#161d26", border: "1px solid #263241", fontSize: 12 }}
                labelFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)}
                formatter={(value: number, name: string) => [fmtInt(value), name]}
              />
              <Legend />
              <Line type="stepAfter" dataKey="strategy" name="Strategy" stroke="#4c9aff"
                dot={false} strokeWidth={1.5} connectNulls />
              <Line type="monotone" dataKey="benchmark" name={result.benchmark_symbol}
                stroke="#8b9bb0" dot={false} strokeWidth={1} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <p className="card-title mb-2">Drawdown (%)</p>
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={dd} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#263241" strokeDasharray="3 3" />
              <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                tickFormatter={tick} stroke="#5d6b7e" fontSize={11} />
              <YAxis stroke="#5d6b7e" fontSize={11} width={48} />
              <Tooltip
                contentStyle={{ background: "#161d26", border: "1px solid #263241", fontSize: 12 }}
                labelFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)}
                formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
              />
              <Area type="stepAfter" dataKey="dd" stroke="#e5534b" fill="#e5534b" fillOpacity={0.25} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="card-title mb-2">Performance by event category</p>
          {Object.keys(result.by_category).length === 0 ? (
            <p className="text-sm text-ink-faint">No trades were made.</p>
          ) : (
            <Table head={["Category", "Return", "Win rate", "Profit factor", "Trades"]}>
              {Object.entries(result.by_category).map(([name, m]) => (
                <tr key={name}>
                  <td className="table-cell capitalize">{label(name)}</td>
                  <td className={`table-cell num ${signClass(m.cumulative_return)}`}>
                    {fmtPct(m.cumulative_return)}
                  </td>
                  <td className="table-cell num">{fmtPct(m.win_rate, 1)}</td>
                  <td className="table-cell num">{fmtNum(m.profit_factor)}</td>
                  <td className="table-cell num">{fmtInt(m.trade_count)}</td>
                </tr>
              ))}
            </Table>
          )}
        </div>
        <div>
          <p className="card-title mb-2">Why signals were not traded</p>
          <Table head={["Reason", "Count"]}>
            {Object.entries(result.no_trade_reasons).map(([reason, count]) => (
              <tr key={reason}>
                <td className="table-cell">{reason}</td>
                <td className="table-cell num">{fmtInt(count)}</td>
              </tr>
            ))}
          </Table>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="card-title mb-2">Assumptions</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-muted">
            {result.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="card-title mb-2">Configuration</p>
          <pre className="overflow-x-auto rounded bg-surface p-3 text-xs text-ink-muted">
            {JSON.stringify(result.config, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

export function StrategyResearch({ refreshKey }: { refreshKey: number }) {
  const [study, reloadStudy] = useApi(api.eventStudy, [refreshKey]);
  const [backtests, reloadBacktests] = useApi(api.backtests, [refreshKey]);
  const [selected, setSelected] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyName>("momentum_continuation");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const firstId = backtests.state === "ready" ? (backtests.data[0]?.run_id ?? null) : null;
  useEffect(() => {
    if (selected === null && firstId) setSelected(firstId);
  }, [firstId, selected]);

  const [detail, reloadDetail] = useApi<BacktestResult | null>(
    () => (selected ? api.backtest(selected) : Promise.resolve(null)),
    [selected],
  );

  const run = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const result = await api.runBacktest(strategy);
      setSelected(result.run_id);
      reloadBacktests();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Backtest failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="Event study: abnormal returns after posts">
        <AsyncView
          result={study}
          reload={reloadStudy}
          emptyTitle="No event study has been run"
          emptyHint="Run `tradebot research event-study` after building features."
          isEmpty={(r) => r.events_total === 0}
        >
          {(report) => <EventStudy report={report} />}
        </AsyncView>
      </Card>

      <Card
        title="Backtests"
        action={
          <div className="flex items-center gap-2">
            <select
              aria-label="Strategy to backtest"
              className="input"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as StrategyName)}
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
            <button type="button" className="btn" onClick={run} disabled={running}>
              {running ? "Running…" : "Run backtest"}
            </button>
          </div>
        }
      >
        {runError && <p className="mb-3 text-sm text-loss">{runError}</p>}
        <AsyncView
          result={backtests}
          reload={reloadBacktests}
          emptyTitle="No backtests have been run"
          emptyHint="Choose a strategy and run a backtest."
        >
          {(rows) => (
            <Table head={["Strategy", "Period", "Return", "Benchmark", "Sharpe", "Max DD", "Trades", ""]}>
              {rows.map((b) => (
                <tr key={b.run_id} className={b.run_id === selected ? "bg-surface" : ""}>
                  <td className="table-cell capitalize">{label(b.strategy)}</td>
                  <td className="table-cell text-ink-muted">
                    {fmtDate(b.period_start)} to {fmtDate(b.period_end)}
                  </td>
                  <td className={`table-cell num ${signClass(b.metrics.cumulative_return)}`}>
                    {fmtPct(b.metrics.cumulative_return)}
                  </td>
                  <td className="table-cell num">
                    {fmtPct(b.benchmark_metrics?.cumulative_return)}
                  </td>
                  <td className="table-cell num">{fmtNum(b.metrics.sharpe_ratio)}</td>
                  <td className="table-cell num">{fmtPct(b.metrics.max_drawdown)}</td>
                  <td className="table-cell num">{fmtInt(b.metrics.trade_count)}</td>
                  <td className="table-cell">
                    <button type="button" className="btn" onClick={() => setSelected(b.run_id)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </AsyncView>
      </Card>

      {selected && (
        <Card title="Backtest detail">
          <AsyncView
            result={detail}
            reload={reloadDetail}
            emptyTitle="Backtest not found"
            isEmpty={(d) => d === null}
          >
            {(d) => (d ? <BacktestDetail result={d} /> : null)}
          </AsyncView>
        </Card>
      )}
    </div>
  );
}
