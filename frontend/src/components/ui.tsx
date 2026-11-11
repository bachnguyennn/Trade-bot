import type { ReactNode } from "react";
import type { DataQuality } from "../api/types";
import type { Async } from "../hooks";

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div
      data-testid="empty-state"
      className="rounded border border-dashed border-surface-border px-4 py-8 text-center"
    >
      <p className="text-sm font-medium text-ink-muted">{title}</p>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className="rounded border border-loss/50 bg-loss/10 px-4 py-4 text-sm"
    >
      <p className="font-medium text-loss">Could not load this section</p>
      <p className="mt-1 text-ink-muted">{message}</p>
      {onRetry && (
        <button type="button" className="btn mt-3" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Loading() {
  return (
    <div data-testid="loading" className="px-4 py-6 text-sm text-ink-faint">
      Loading…
    </div>
  );
}

/**
 * Render the right state for a request. Children only run when real data arrived, so a
 * section can never show numbers it did not get from the API.
 */
export function AsyncView<T>({
  result,
  reload,
  emptyTitle,
  emptyHint,
  isEmpty,
  children,
}: {
  result: Async<T>;
  reload?: () => void;
  emptyTitle: string;
  emptyHint?: string;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (result.state === "loading") return <Loading />;
  if (result.state === "error") return <ErrorState message={result.message} onRetry={reload} />;
  if (result.state === "missing") return <EmptyState title={emptyTitle} hint={emptyHint} />;
  const empty = isEmpty
    ? isEmpty(result.data)
    : Array.isArray(result.data) && result.data.length === 0;
  if (empty) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(result.data)}</>;
}

export function Card({
  title,
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card p-4">
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="card-title">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: string;
}) {
  return (
    <div className="card p-4">
      <p className="card-title">{label}</p>
      <p className={`num mt-2 text-2xl font-semibold ${tone ?? "text-ink"}`}>{value}</p>
      {note && <p className="mt-1 text-xs text-ink-faint">{note}</p>}
    </div>
  );
}

const QUALITY_TEXT: Record<DataQuality, { text: string; className: string; title: string }> = {
  consolidated: {
    text: "Consolidated",
    className: "border-gain/50 text-gain",
    title: "Full-market (consolidated) prices.",
  },
  delayed: {
    text: "Delayed data",
    className: "border-warn/50 text-warn",
    title: "Prices are delayed and may differ from consolidated real-time prices.",
  },
  partial_venue: {
    text: "Single venue",
    className: "border-warn/50 text-warn",
    title: "Prices come from one exchange only and can differ from the full market.",
  },
  synthetic: {
    text: "Synthetic test data",
    className: "border-loss/50 text-loss",
    title: "Generated test data. Not real market prices.",
  },
};

export function DataQualityBadge({ quality }: { quality: DataQuality | null | undefined }) {
  if (!quality) return null;
  const info = QUALITY_TEXT[quality];
  return (
    <span
      title={info.title}
      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${info.className}`}
    >
      {info.text}
    </span>
  );
}

export function Pill({ children, tone = "muted" }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    muted: "border-surface-border text-ink-muted",
    gain: "border-gain/50 text-gain",
    loss: "border-loss/50 text-loss",
    warn: "border-warn/50 text-warn",
    accent: "border-accent/50 text-accent",
  };
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs ${tones[tone] ?? tones.muted}`}>
      {children}
    </span>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-surface-border">
            {head.map((h) => (
              <th key={h} className="table-head">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-border/60">{children}</tbody>
      </table>
    </div>
  );
}
