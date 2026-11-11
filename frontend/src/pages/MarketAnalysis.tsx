import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { Interval, MarketEvent, StockCandle } from "../api/types";
import { AsyncView, Card, DataQualityBadge, Table } from "../components/ui";
import { fmtBps, fmtDate, fmtNum, fmtPct, fmtTime, label, signClass } from "../format";
import { useApi } from "../hooks";

function PriceChart({ candles, events }: { candles: StockCandle[]; events: MarketEvent[] }) {
  const data = useMemo(
    () => candles.map((c) => ({ t: new Date(c.ts).getTime(), close: c.close })),
    [candles],
  );
  const first = data[0]?.t ?? 0;
  const last = data[data.length - 1]?.t ?? 0;
  const markers = events
    .map((e) => ({ id: e.event_id, t: new Date(e.available_at).getTime() }))
    .filter((m) => m.t >= first && m.t <= last)
    .slice(0, 150);

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#263241" strokeDasharray="3 3" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)}
            stroke="#5d6b7e"
            fontSize={11}
          />
          <YAxis domain={["auto", "auto"]} stroke="#5d6b7e" fontSize={11} width={56} />
          <Tooltip
            contentStyle={{ background: "#161d26", border: "1px solid #263241", fontSize: 12 }}
            labelFormatter={(t: number) => fmtTime(new Date(t).toISOString())}
            formatter={(value: number) => [fmtNum(value), "Close"]}
          />
          {markers.map((m) => (
            <ReferenceLine key={m.id} x={m.t} stroke="#d4a72c" strokeOpacity={0.45} />
          ))}
          <Line type="monotone" dataKey="close" stroke="#4c9aff" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MarketAnalysis({ refreshKey }: { refreshKey: number }) {
  const [symbol, setSymbol] = useState("NUE");
  const [interval, setInterval] = useState<Interval>("1d");
  const [universe] = useApi(api.universe, [refreshKey]);
  const [candles, reloadCandles] = useApi(
    () => api.candles(symbol, interval, 750),
    [symbol, interval, refreshKey],
  );
  const [events] = useApi(() => api.events({ symbol, limit: 500 }), [symbol, refreshKey]);
  const [features, reloadFeatures] = useApi(
    () => api.features({ symbol, limit: 200 }),
    [symbol, refreshKey],
  );
  const [predictions, reloadPredictions] = useApi(
    () => api.predictions({ symbol, limit: 20 }),
    [symbol, refreshKey],
  );
  const eventList = events.state === "ready" ? events.data : [];
  const eventText = useMemo(
    () => new Map(eventList.map((e) => [e.event_id, e.text])),
    [eventList],
  );

  return (
    <div className="space-y-4">
      <Card
        title="Stock market analysis"
        action={
          <div className="flex gap-2">
            <select
              aria-label="Symbol"
              className="input"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              {universe.state === "ready" ? (
                universe.data.map((m) => (
                  <option key={m.symbol} value={m.symbol}>
                    {m.symbol} · {m.name}
                  </option>
                ))
              ) : (
                <option value={symbol}>{symbol}</option>
              )}
            </select>
            <select
              aria-label="Interval"
              className="input"
              value={interval}
              onChange={(e) => setInterval(e.target.value as Interval)}
            >
              <option value="1d">Daily</option>
              <option value="1h">Hourly</option>
              <option value="5m">5 minutes</option>
            </select>
          </div>
        }
      >
        <AsyncView
          result={candles}
          reload={reloadCandles}
          emptyTitle={`No ${interval} candles stored for ${symbol}`}
          emptyHint="Run `tradebot ingest market` for this interval."
        >
          {(rows) => (
            <>
              <div className="mb-2 flex items-center gap-3 text-xs text-ink-faint">
                <DataQualityBadge quality={rows[rows.length - 1]?.quality} />
                <span>
                  {fmtDate(rows[0]?.ts)} to {fmtDate(rows[rows.length - 1]?.ts)} · source{" "}
                  {rows[0]?.source}
                </span>
                <span>Vertical lines mark events mapped to this symbol.</span>
              </div>
              <PriceChart candles={rows} events={eventList} />
            </>
          )}
        </AsyncView>
      </Card>

      <Card title={`Before and after: measured reactions for ${symbol}`}>
        <AsyncView
          result={features}
          reload={reloadFeatures}
          emptyTitle="No measurements for this symbol"
          emptyHint="Run `tradebot build features` after importing posts and candles."
          isEmpty={(rows) => rows.filter((f) => f.available).length === 0}
        >
          {(rows) => (
            <Table head={["Event", "Window", "Entry", "Exit", "Return", "Abnormal", "Post"]}>
              {rows
                .filter((f) => f.available)
                .slice(0, 40)
                .map((f) => (
                  <tr key={`${f.event_id}-${f.window}`}>
                    <td className="table-cell whitespace-nowrap text-ink-muted">
                      {fmtTime(f.anchor_ts)}
                    </td>
                    <td className="table-cell">{label(f.window)}</td>
                    <td className="table-cell num">{fmtNum(f.entry_price)}</td>
                    <td className="table-cell num">{fmtNum(f.exit_price)}</td>
                    <td className={`table-cell num ${signClass(f.ret)}`}>{fmtPct(f.ret)}</td>
                    <td className={`table-cell num ${signClass(f.abnormal_ret)}`}>
                      {fmtBps(f.abnormal_ret)}
                    </td>
                    <td className="table-cell max-w-xs truncate text-xs text-ink-faint">
                      {eventText.get(f.event_id) ?? ""}
                    </td>
                  </tr>
                ))}
            </Table>
          )}
        </AsyncView>
      </Card>

      <Card title={`Prediction confidence for ${symbol}`}>
        <AsyncView
          result={predictions}
          reload={reloadPredictions}
          emptyTitle="No predictions for this symbol"
          emptyHint="Train a model with `tradebot model train`."
        >
          {(rows) => (
            <Table head={["Predicted at", "Window", "Direction", "P(up)", "Confidence", "Model"]}>
              {rows.map((p) => (
                <tr key={p.prediction_id}>
                  <td className="table-cell text-ink-muted">{fmtTime(p.predicted_at)}</td>
                  <td className="table-cell">{p.window}</td>
                  <td className="table-cell uppercase">{p.direction}</td>
                  <td className="table-cell num">{fmtPct(p.prob_up, 1)}</td>
                  <td className="table-cell num">{fmtPct(p.confidence, 1)}</td>
                  <td className="table-cell text-xs text-ink-faint">{p.model_version}</td>
                </tr>
              ))}
            </Table>
          )}
        </AsyncView>
      </Card>
    </div>
  );
}
