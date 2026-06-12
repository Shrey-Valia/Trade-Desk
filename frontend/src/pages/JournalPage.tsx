import { useMemo, useState } from "react";

import { DayModal } from "@/components/journal/DayModal";
import { JournalCalendar } from "@/components/journal/JournalCalendar";
import { PageHeader } from "@/components/layout/PageHeader";
import { TradeEntryModal } from "@/components/positions/journal/TradeEntryModal";
import { TradeList } from "@/components/positions/journal/TradeList";
import { useTrades } from "@/hooks/useTrades";
import { downloadCsv, tradesToCsv } from "@/lib/exportCsv";
import { useSelectedTicker } from "@/stores/selectedTicker";
import type { Trade } from "@/types/journal";

type View = "calendar" | "list";
type PaperScope = "all" | "paper" | "live";

/**
 * /journal — the trade ledger + learning tool.
 *
 * Primary view: monthly P&L calendar (Topstep style). Clicking a
 * populated day opens a detail modal with each trade expanded — legs,
 * note, tags and the intratrade summary. Secondary view: the flat trade
 * table, one click away via the view toggle.
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

  const { data, isError, refetch } = useTrades();
  const allTrades = data?.trades ?? [];
  // JOURNAL is closed-only — open positions live on the CHART view's
  // chain panel now. The calendar view already bucketed by exit_date so
  // open trades never showed there; the list view needs explicit filtering.
  const trades = useMemo(
    () => allTrades.filter((t) => t.status === "closed"),
    [allTrades],
  );

  // Id → trade lookup, shared with the calendar (pips / tag-dot) and the
  // day modal (trade detail) so both render from the same loaded rows.
  const tradesById = useMemo(() => {
    const m = new Map<number, Trade>();
    for (const t of trades) m.set(t.id, t);
    return m;
  }, [trades]);

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

  // The day modal pulls trades whose IDs match the active day's bucket.
  // Filtering by ID keeps the modal exactly in sync with what the
  // calendar counted — no drift from a separate query.
  const dayTrades: Trade[] = useMemo(() => {
    if (!activeDay) return [];
    const ids = new Set(activeDay.trade_ids);
    return trades.filter((t) => ids.has(t.id));
  }, [trades, activeDay]);

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Journal"
        subtitle={
          trades.length === 0
            ? "Closed trades will appear here once you close a position."
            : `${trades.length} closed trade${trades.length === 1 ? "" : "s"}`
        }
      />
      <Toolbar
        view={view}
        onViewChange={(v) => {
          setView(v);
          setActiveDay(null);
        }}
        paperScope={paperScope}
        onPaperScopeChange={setPaperScope}
        onAddTrade={() => setModalOpen(true)}
        onExport={() => {
          // Export honors the paper/live scope filter; closed trades
          // only, matching what the page shows.
          const scoped =
            isPaperFilter === null
              ? trades
              : trades.filter((t) => t.is_paper === isPaperFilter);
          const stamp = new Date().toISOString().slice(0, 10);
          downloadCsv(`trade-desk-journal-${stamp}.csv`, tradesToCsv(scoped));
        }}
        exportDisabled={trades.length === 0}
      />
      <main className="flex-1 min-h-0 flex flex-col">
        {view === "calendar" ? (
          <div className="flex-1 min-h-0">
            <JournalCalendar
              isPaper={isPaperFilter}
              tradesById={tradesById}
              onDayClick={(d) => setActiveDay({ date: d.date, trade_ids: d.trade_ids })}
            />
          </div>
        ) : (
          <div className="flex-1 min-h-0 border-t border-hairline">
            <TradeList
              trades={listTrades}
              scope={listScope}
              onScopeChange={setListScope}
              selectedSymbol={selectedSymbol}
              onAddTrade={() => setModalOpen(true)}
              loadFailed={isError}
              onRetry={() => refetch()}
            />
          </div>
        )}
      </main>
      {activeDay && (
        <DayModal
          date={activeDay.date}
          trades={dayTrades}
          onClose={() => setActiveDay(null)}
        />
      )}
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
  onExport,
  exportDisabled,
}: {
  view: View;
  onViewChange: (v: View) => void;
  paperScope: PaperScope;
  onPaperScopeChange: (s: PaperScope) => void;
  onAddTrade: () => void;
  onExport: () => void;
  exportDisabled: boolean;
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
      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={onExport}
          disabled={exportDisabled}
          title={
            exportDisabled
              ? "Nothing to export yet"
              : "Download the closed trades shown (respects the paper/live filter) as CSV"
          }
          className="h-6 px-2 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ borderRadius: 0 }}
        >
          Export CSV
        </button>
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
