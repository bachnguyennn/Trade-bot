import { useState } from "react";
import { api } from "../api/client";
import type { EventCategory, MarketEvent } from "../api/types";
import { AsyncView, Card, Pill, Table } from "../components/ui";
import { fmtBps, fmtPct, fmtTime, label } from "../format";
import { useApi } from "../hooks";

const CATEGORIES: EventCategory[] = [
  "tariffs_trade",
  "energy_oil",
  "technology_semiconductors",
  "defence",
  "banking_monetary_policy",
  "immigration_employment",
  "government_spending",
  "sanctions_international",
];

function EventDetails({ eventId }: { eventId: string }) {
  const [detail, reload] = useApi(() => api.event(eventId), [eventId]);
  return (
    <AsyncView result={detail} reload={reload} emptyTitle="Event not found" isEmpty={() => false}>
      {(d) => (
        <div className="mt-3 space-y-4 border-t border-surface-border pt-3">
          <div>
            <p className="card-title mb-2">Posts in this event</p>
            <Table head={["Published", "Collected", "Mode", "Text"]}>
              {d.posts.map((post) => (
                <tr key={post.post_id}>
                  <td className="table-cell whitespace-nowrap">{fmtTime(post.published_at)}</td>
                  <td className="table-cell whitespace-nowrap">{fmtTime(post.retrieved_at)}</td>
                  <td className="table-cell">{post.ingestion_mode}</td>
                  <td className="table-cell">
                    <a className="text-accent hover:underline" href={post.url} target="_blank" rel="noreferrer">
                      {post.text.slice(0, 160) || "(media only)"}
                    </a>
                  </td>
                </tr>
              ))}
            </Table>
          </div>

          <div>
            <p className="card-title mb-2">Model predictions</p>
            {d.predictions.length === 0 ? (
              <p className="text-sm text-ink-faint">
                No out-of-sample prediction exists for this event.
              </p>
            ) : (
              <Table head={["Symbol", "Window", "Direction", "P(up)", "Expected", "Confidence", "Model"]}>
                {d.predictions.map((p) => (
                  <tr key={p.prediction_id}>
                    <td className="table-cell num font-semibold">{p.symbol}</td>
                    <td className="table-cell">{p.window}</td>
                    <td className="table-cell uppercase">{p.direction}</td>
                    <td className="table-cell num">{fmtPct(p.prob_up, 1)}</td>
                    <td className="table-cell num">{fmtBps(p.expected_abnormal_return)}</td>
                    <td className="table-cell num">{fmtPct(p.confidence, 1)}</td>
                    <td className="table-cell text-xs text-ink-faint">{p.model_version}</td>
                  </tr>
                ))}
              </Table>
            )}
          </div>

          <div>
            <p className="card-title mb-2">Measured reaction (abnormal return vs benchmark)</p>
            <Table head={["Symbol", "Window", "Return", "Benchmark", "Abnormal", "Note"]}>
              {d.features
                .filter((f) => f.available || f.window === "1d")
                .map((f) => (
                  <tr key={`${f.symbol}-${f.window}`}>
                    <td className="table-cell num font-semibold">{f.symbol}</td>
                    <td className="table-cell">{label(f.window)}</td>
                    <td className="table-cell num">{fmtPct(f.ret)}</td>
                    <td className="table-cell num">{fmtPct(f.benchmark_ret)}</td>
                    <td className="table-cell num">{fmtBps(f.abnormal_ret)}</td>
                    <td className="table-cell text-xs text-ink-faint">
                      {f.available
                        ? f.tradable
                          ? f.shifted_to_open
                            ? "entered at next open"
                            : ""
                          : "descriptive only, not tradable"
                        : `unavailable: ${f.unavailable_reason ?? "unknown"}`}
                    </td>
                  </tr>
                ))}
            </Table>
          </div>
        </div>
      )}
    </AsyncView>
  );
}

function EventRow({ event }: { event: MarketEvent }) {
  const [open, setOpen] = useState(false);
  const companies = event.entities.filter((e) => e.type === "company" || e.type === "ticker");
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
        <span>Published {fmtTime(event.published_at)}</span>
        <span>·</span>
        <span>Available to system {fmtTime(event.available_at)}</span>
        {event.post_ids.length > 1 && <Pill>{event.post_ids.length} posts</Pill>}
      </div>
      <p className="mt-2 text-sm leading-relaxed">{event.text}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {event.categories.map((c) => (
          <Pill key={c} tone="accent">
            {label(c)}
          </Pill>
        ))}
        {companies.map((e) => (
          <Pill key={e.text} tone="warn">
            {e.text}
            {e.symbol ? ` (${e.symbol})` : ""}
          </Pill>
        ))}
        {event.symbols.map((s) => (
          <span key={s} className="num rounded bg-surface px-2 py-0.5 text-xs text-ink-muted">
            {s}
          </span>
        ))}
      </div>
      <button type="button" className="btn mt-3" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide details" : "Show collection time, predictions, and reaction"}
      </button>
      {open && <EventDetails eventId={event.event_id} />}
    </li>
  );
}

export function EventFeed({ refreshKey }: { refreshKey: number }) {
  const [category, setCategory] = useState<EventCategory | "">("");
  const [events, reload] = useApi(
    () => api.events({ limit: 50, category }),
    [category, refreshKey],
  );

  return (
    <div className="space-y-4">
      <Card
        title="Political event feed"
        action={
          <select
            aria-label="Filter by category"
            className="input"
            value={category}
            onChange={(e) => setCategory(e.target.value as EventCategory | "")}
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {label(c)}
              </option>
            ))}
          </select>
        }
      >
        <p className="text-xs text-ink-faint">
          Posts classified as market-relevant by keyword rules. Categories and affected symbols
          are a rule-based mapping, not a statement that a post moved any price.
        </p>
      </Card>
      <AsyncView
        result={events}
        reload={reload}
        emptyTitle="No market events"
        emptyHint="Import posts and run `tradebot build events`, or change the filter."
      >
        {(rows) => (
          <ul className="space-y-3">
            {rows.map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
          </ul>
        )}
      </AsyncView>
    </div>
  );
}
