import { useState } from "react";
import { api } from "../api/client";
import type { OrderStatus } from "../api/types";
import { AsyncView, Card, Pill, StatCard, Table } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, fmtTime, signClass } from "../format";
import { useApi } from "../hooks";

const STATUS_TONE: Record<OrderStatus, string> = {
  pending: "muted",
  submitted: "accent",
  filled: "gain",
  rejected: "loss",
  cancelled: "muted",
  blocked: "warn",
};

export function PaperTrading({ refreshKey }: { refreshKey: number }) {
  const [portfolio, reloadPortfolio] = useApi(api.portfolio, [refreshKey]);
  const [risk, reloadRisk] = useApi(api.risk, [refreshKey]);
  const [orders, reloadOrders] = useApi(api.orders, [refreshKey]);
  const [busy, setBusy] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const toggleKillSwitch = async (enabled: boolean) => {
    setBusy(true);
    setSwitchError(null);
    try {
      await api.setKillSwitch(enabled);
      reloadRisk();
    } catch (error) {
      setSwitchError(error instanceof Error ? error.message : "Could not change the kill switch");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="card border-warn/40 px-4 py-3 text-sm text-ink-muted">
        <strong className="text-warn">Paper trading only.</strong> Orders here are simulated or
        sent to a paper account. This platform cannot place real-money orders.
      </div>

      <Card title="Account">
        <AsyncView
          result={portfolio}
          reload={reloadPortfolio}
          emptyTitle="No account data"
          isEmpty={() => false}
        >
          {(p) => (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <StatCard label="Account value" value={fmtMoney(p.equity)} />
              <StatCard label="Cash" value={fmtMoney(p.cash)} />
              <StatCard label="Day P&L" value={fmtMoney(p.day_pnl)} tone={signClass(p.day_pnl)} />
              <StatCard label="Gross exposure" value={fmtPct(p.gross_exposure, 1)} />
              <StatCard label="Broker" value={p.broker} />
            </div>
          )}
        </AsyncView>
      </Card>

      <Card title="Risk controls">
        <AsyncView result={risk} reload={reloadRisk} emptyTitle="No risk state" isEmpty={() => false}>
          {(r) => (
            <div className="flex flex-wrap items-center gap-3">
              <Pill tone={r.kill_switch ? "loss" : "gain"}>
                Kill switch {r.kill_switch ? "ON: no new orders" : "off"}
              </Pill>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => toggleKillSwitch(!r.kill_switch)}
              >
                {r.kill_switch ? "Release kill switch" : "Stop all new orders"}
              </button>
              <Pill tone={r.loss_limit_breached ? "loss" : "muted"}>
                Daily loss limit {fmtPct(r.daily_loss_limit_pct, 1)}
                {r.loss_limit_breached ? ": reached" : ""}
              </Pill>
              <Pill tone={r.market_open ? "gain" : "muted"}>
                Market {r.market_open ? "open" : "closed"}
                {r.enforce_market_hours ? "" : " (hours not enforced)"}
              </Pill>
              <span className="text-xs text-ink-faint">Trading day {r.day}</span>
              {switchError && <span className="text-sm text-loss">{switchError}</span>}
            </div>
          )}
        </AsyncView>
      </Card>

      <Card title="Open positions">
        <AsyncView
          result={portfolio}
          reload={reloadPortfolio}
          emptyTitle="No open positions"
          isEmpty={(p) => p.positions.length === 0}
        >
          {(p) => (
            <Table head={["Symbol", "Quantity", "Average price", "Market value"]}>
              {p.positions.map((position) => (
                <tr key={position.symbol}>
                  <td className="table-cell num font-semibold">{position.symbol}</td>
                  <td className={`table-cell num ${signClass(position.qty)}`}>
                    {fmtNum(position.qty, 4)}
                  </td>
                  <td className="table-cell num">{fmtNum(position.avg_price)}</td>
                  <td className="table-cell num">{fmtMoney(position.market_value)}</td>
                </tr>
              ))}
            </Table>
          )}
        </AsyncView>
      </Card>

      <Card title="Orders">
        <AsyncView
          result={orders}
          reload={reloadOrders}
          emptyTitle="No paper orders yet"
          emptyHint="Orders appear when a live ingestion run produces a trade signal."
        >
          {(rows) => (
            <Table head={["Created", "Symbol", "Side", "Quantity", "Status", "Fill price", "Reason"]}>
              {rows.map((o) => (
                <tr key={o.order_id}>
                  <td className="table-cell whitespace-nowrap text-ink-muted">
                    {fmtTime(o.created_at)}
                  </td>
                  <td className="table-cell num font-semibold">{o.symbol}</td>
                  <td className={`table-cell uppercase ${o.side === "buy" ? "text-gain" : "text-loss"}`}>
                    {o.side}
                  </td>
                  <td className="table-cell num">{o.qty > 0 ? fmtNum(o.qty, 4) : "—"}</td>
                  <td className="table-cell">
                    <Pill tone={STATUS_TONE[o.status]}>{o.status}</Pill>
                  </td>
                  <td className="table-cell num">{fmtNum(o.filled_price)}</td>
                  <td className="table-cell text-xs text-ink-faint">{o.reject_reason ?? ""}</td>
                </tr>
              ))}
            </Table>
          )}
        </AsyncView>
      </Card>
    </div>
  );
}
