import { useMemo, useState } from "react";

import { JournalCalendar } from "@/components/journal/JournalCalendar";
import { PageHeader } from "@/components/layout/PageHeader";
import { TradeEntryModal } from "@/components/positions/journal/TradeEntryModal";
import { TradeList } from "@/components/positions/journal/TradeList";
import { useTrades } from "@/hooks/useTrades";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { STRATEGY_LABELS, type Trade } from "@/types/journal";

type View = "calendar" | "list";
type PaperScope = "all" | "paper" | "live";

/**
 * /journal — Step 2 of the UI revamp.
 *
 * Primary view: monthly P&L calendar (Topstep style). Clicking a
 * populated day surfaces that day's trades as a strip below the grid.
 * Secondary view: the flat trade table (the previous content of this
 * page) one click away via the view toggle at the top.
 *
 * Both views share the paper/live scope filter and the + Log Trade
 * button so behavior is consistent across modes.
 */
export function JournalPage() {
  const selectedSymbol = useSelectedTicker((s) => s.symbol);
  const [view, setView] = useState<View>("calendar");
  const [paperScope, setPaperScope] = useState<PaperScope>("all");
  const [listScope, setListScope] = useState<"current" | "all">("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [activeDay, setActiveDay] = useState<{ date: string; trade_ids: number[] } | null>(null);

  const { data } = useTrades();
  const trades = data?.trades ?? [];

  const isPaperFilter: boolean | null =
    paperScope === "all" ? null : paperScope === "paper";

  // For the list view, filter on selected-symbol + paper scope.
  const listTrades = useMemo(() => {
    let out = trades;
    if (isPaperFilter !== null) {
      out = out.filter((t) => t.is_paper === isPaperFilter);
    }
    if (listScope === "current" && selectedSymbol) {
      out = out.filter((t) => t.symbol === selectedSymbol);
    }
    return out;
  }, [trades, isPaperFilter, listScope, selectedSymbol]);

  // For the day-detail strip, pull the trades whose IDs match the
  // active day's bucket. Filter is by ID so the list reflects exactly
  // what the calendar counted — no risk of drift from a separate filter.
  const dayTrades: Trade[] = useMemo(() => {
    if (!activeDay) return [];
    const ids = new Set(activeDay.trade_ids);
    return trades.filter((t) => ids.has(t.id));
  }, [trades, activeDay]);

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Journal" subtitle={`${trades.length} trades`} />
      <Toolbar
        view={view}
        onViewChange={(v) => {
          setView(v);
          setActiveDay(null);
        }}
        paperScope={paperScope}
        onPaperScopeChange={setPaperScope}
        onAddTrade={() => setModalOpen(true)}
      />
      <main className="flex-1 min-h-0 flex flex-col">
        {view === "calendar" ? (
          <>
            <div className="flex-1 min-h-0">
              <JournalCalendar
                isPaper={isPaperFilter}
                onDayClick={(d) => setActiveDay({ date: d.date, trade_ids: d.trade_ids })}
              />
            </div>
            {activeDay && (
              <DayDetailStrip
                date={activeDay.date}
                trades={dayTrades}
                onClose={() => setActiveDay(null)}
              />
            )}
          </>
        ) : (
          <div className="flex-1 min-h-0 border-t border-hairline">
            <TradeList
              trades={listTrades}
              scope={listScope}
              onScopeChange={setListScope}
              selectedSymbol={selectedSymbol}
              onAddTrade={() => setModalOpen(true)}
            />
          </div>
        )}
      </main>
      <TradeEntryModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}

function Toolbar({
  view,
  onViewChange,
  paperScope,
  onPaperScopeChange,
  onAddTrade,
}: {
  view: View;
  onViewChange: (v: View) => void;
  paperScope: PaperScope;
  onPaperScopeChange: (s: PaperScope) => void;
  onAddTrade: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-hairline bg-tier-0 shrink-0">
      {/* View toggle */}
      <div className="flex items-stretch border border-hairline" style={{ borderRadius: 0 }}>
        {(["calendar", "list"] as View[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => onViewChange(v)}
            className={[
              "h-6 px-2 text-tiny uppercase tracking-label-up",
              v === view
                ? "text-amber bg-tier-2"
                : "text-fg-secondary hover:bg-tier-2 hover:text-fg-primary",
              v !== "calendar" ? "border-l border-hairline" : "",
            ].join(" ")}
          >
            {v}
          </button>
        ))}
      </div>
      {/* Paper/live filter */}
      <div className="flex items-stretch gap-1 ml-2">
        {(["all", "paper", "live"] as PaperScope[]).map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onPaperScopeChange(opt)}
            className={[
              "h-6 px-2 text-tiny uppercase tracking-label-up border",
              paperScope === opt
                ? "border-amber text-amber bg-tier-1"
                : "border-hairline text-fg-tertiary hover:bg-tier-2",
            ].join(" ")}
            style={{ borderRadius: 0 }}
          >
            {opt}
          </button>
        ))}
      </div>
      <div className="ml-auto">
        <button
          type="button"
          onClick={onAddTrade}
          className="h-6 px-2 text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2"
          style={{ borderRadius: 0 }}
        >
          + Log Trade
        </button>
      </div>
    </div>
  );
}

function DayDetailStrip({
  date,
  trades,
  onClose,
}: {
  date: string;
  trades: Trade[];
  onClose: () => void;
}) {
  const niceDate = formatNiceDate(date);
  const totalPnl = trades.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  return (
    <section className="border-t border-hairline bg-tier-0 shrink-0">
      <header className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <div className="flex items-baseline gap-3">
          <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
            {niceDate}
          </span>
          <span className="text-tiny text-fg-tertiary tabular-nums">
            {trades.length} trade{trades.length === 1 ? "" : "s"}
          </span>
          <span
            className={[
              "text-tiny tabular-nums",
              totalPnl > 0 ? "text-bullish" : totalPnl < 0 ? "text-bearish" : "text-fg-secondary",
            ].join(" ")}
          >
            {formatDollar(totalPnl)}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-tiny text-fg-tertiary hover:text-fg-primary"
          aria-label="Close day detail"
        >
          ×
        </button>
      </header>
      <table className="w-full text-tiny tabular-nums">
        <thead>
          <tr className="text-fg-secondary uppercase tracking-label-up">
            <th className="px-2 py-1 text-left font-normal" style={{ fontSize: 9 }}>Sym</th>
            <th className="px-2 py-1 text-left font-normal" style={{ fontSize: 9 }}>Strategy</th>
            <th className="px-2 py-1 text-right font-normal" style={{ fontSize: 9 }}>Net</th>
            <th className="px-2 py-1 text-right font-normal" style={{ fontSize: 9 }}>Realized</th>
            <th className="px-2 py-1 text-right font-normal" style={{ fontSize: 9 }}>R</th>
            <th className="px-2 py-1 text-left font-normal" style={{ fontSize: 9 }}>Tag</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id} className="border-t border-hairline">
              <td className="px-2 py-1 text-left text-fg-primary">{t.symbol}</td>
              <td className="px-2 py-1 text-left text-fg-primary">
                {STRATEGY_LABELS[t.strategy] ?? t.strategy}
              </td>
              <td className={`px-2 py-1 text-right ${t.net_debit_credit < 0 ? "text-bullish" : "text-fg-primary"}`}>
                {formatDollar(t.net_debit_credit)}
              </td>
              <td className={`px-2 py-1 text-right ${pnlClass(t.realized_pnl ?? null)}`}>
                {t.realized_pnl == null ? "—" : formatDollar(t.realized_pnl)}
              </td>
              <td className={`px-2 py-1 text-right ${pnlClass(t.r_multiple ?? null)}`}>
                {t.r_multiple == null ? "—" : `${t.r_multiple >= 0 ? "+" : "−"}${Math.abs(t.r_multiple).toFixed(2)}R`}
              </td>
              <td className="px-2 py-1 text-left">
                <span
                  className={
                    t.is_paper
                      ? "border-l-2 border-cyan pl-1.5 text-cyan uppercase tracking-label-up"
                      : "border-l-2 border-amber pl-1.5 text-amber uppercase tracking-label-up"
                  }
                  style={{ fontSize: 9 }}
                >
                  {t.is_paper ? "Paper" : "Live"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function formatDollar(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pnlClass(v: number | null): string {
  if (v == null) return "text-fg-tertiary";
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}

function formatNiceDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
