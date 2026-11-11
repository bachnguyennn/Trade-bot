import { useCallback, useState } from "react";
import { useStream } from "./hooks";
import { EventFeed } from "./pages/EventFeed";
import { MarketAnalysis } from "./pages/MarketAnalysis";
import { ModelAnalytics } from "./pages/ModelAnalytics";
import { Overview } from "./pages/Overview";
import { PaperTrading } from "./pages/PaperTrading";
import { StrategyResearch } from "./pages/StrategyResearch";

const SECTIONS = [
  { id: "overview", name: "Overview", component: Overview },
  { id: "events", name: "Political Event Feed", component: EventFeed },
  { id: "market", name: "Stock Market Analysis", component: MarketAnalysis },
  { id: "strategy", name: "Strategy Research", component: StrategyResearch },
  { id: "trading", name: "Paper Trading", component: PaperTrading },
  { id: "models", name: "Model Analytics", component: ModelAnalytics },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

export default function App() {
  const [active, setActive] = useState<SectionId>("overview");
  const [refreshKey, setRefreshKey] = useState(0);
  const [liveCount, setLiveCount] = useState(0);

  // New events and orders from the live stream refresh whatever is on screen.
  const onMessage = useCallback((message: { type: string }) => {
    if (message.type === "event" || message.type === "order") {
      setLiveCount((n) => n + 1);
      setRefreshKey((k) => k + 1);
    }
  }, []);
  const connected = useStream(onMessage);

  const Section = SECTIONS.find((s) => s.id === active)?.component ?? Overview;

  return (
    <div className="min-h-screen">
      <header className="border-b border-surface-border bg-surface-raised">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">TradeBot Research</h1>
            <p className="text-xs text-ink-faint">
              Event-driven market research · paper trading only · not investment advice
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span
              className={connected ? "text-gain" : "text-ink-faint"}
              title="Live stream of new events and orders"
            >
              ● {connected ? "Live stream connected" : "Live stream offline"}
              {liveCount > 0 ? ` · ${liveCount} updates` : ""}
            </span>
            <button type="button" className="btn" onClick={() => setRefreshKey((k) => k + 1)}>
              Refresh
            </button>
          </div>
        </div>
        <nav aria-label="Sections" className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4">
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              type="button"
              aria-current={active === section.id ? "page" : undefined}
              onClick={() => setActive(section.id)}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
                active === section.id
                  ? "border-accent text-ink"
                  : "border-transparent text-ink-muted hover:text-ink"
              }`}
            >
              {section.name}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">
        <Section refreshKey={refreshKey} />
      </main>
    </div>
  );
}
