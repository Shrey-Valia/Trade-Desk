import { useState } from "react";

import { useUpdateTrade } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { STRATEGY_LABELS, type Trade } from "@/types/journal";

interface Props {
  trades: Trade[];
  scope: "current" | "all";
  onScopeChange: (s: "current" | "all") => void;
  selectedSymbol: string | null;
  onAddTrade: () => void;
}

/**
 * Compact, hairline-bordered table of journaled trades.
 *
 * Columns: SYM · STRATEGY · ENTRY · DTE · NET · STATUS · TAG · ✕
 * Rows clickable in Phase 2 to draw on the chart; this phase the click
 * opens an inline close form. Paper trades get a small cyan PAPER chip,
 * live-journaled trades get an amber LIVE chip — same color semantic as
 * everywhere else in the system.
 */
export function TradeList({
  trades,
  scope,
  onScopeChange,
  selectedSymbol,
  onAddTrade,
}: Props) {
  const [closingId, setClosingId] = useState<number | null>(null);
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const toggleActive = useActivePosition((s) => s.toggle);
  const setSelectedSymbol = useSelectedTicker((s) => s.setSymbol);

  const onRowClick = (trade: Trade) => {
    // Auto-switch the chart to the trade's symbol so the position
    // overlay lands on a chart that actually shows that ticker. If the
    // user re-clicks the active row, deselect (toggle behavior).
    if (trade.symbol !== selectedSymbol) {
      setSelectedSymbol(trade.symbol);
    }
    toggleActive(trade.id);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <Header
        count={trades.length}
        scope={scope}
        onScopeChange={onScopeChange}
        selectedSymbol={selectedSymbol}
        onAddTrade={onAddTrade}
      />
      <div className="flex-1 min-h-0 overflow-y-auto">
        {trades.length === 0 ? (
          <div className="px-3 py-6 text-tiny text-fg-tertiary text-center">
            No trades logged yet. Click <span className="text-fg-primary">+ Log Trade</span> to start.
          </div>
        ) : (
          <table className="w-full text-tiny tabular-nums">
            <thead>
              <tr className="text-fg-secondary uppercase tracking-label-up">
                <Th className="text-left">Sym</Th>
                <Th className="text-left">Strategy</Th>
                <Th className="text-right">Entry</Th>
                <Th className="text-right">DTE</Th>
                <Th className="text-right">Net</Th>
                <Th className="text-right">Realized</Th>
                <Th className="text-left">Status</Th>
                <Th className="text-left">Tag</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <TradeRow
                  key={t.id}
                  trade={t}
                  active={activeTradeId === t.id}
                  isClosing={closingId === t.id}
                  onSelect={() => onRowClick(t)}
                  onStartClose={() => setClosingId(t.id)}
                  onCancelClose={() => setClosingId(null)}
                  onClosed={() => setClosingId(null)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Header({
  count,
  scope,
  onScopeChange,
  selectedSymbol,
  onAddTrade,
}: {
  count: number;
  scope: "current" | "all";
  onScopeChange: (s: "current" | "all") => void;
  selectedSymbol: string | null;
  onAddTrade: () => void;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 border-b border-hairline shrink-0">
      <div className="flex items-baseline gap-3">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Journal
        </span>
        <span className="text-tiny text-fg-tertiary tabular-nums">({count})</span>
      </div>
      <div className="flex items-stretch gap-2">
        <ScopeToggle scope={scope} onScopeChange={onScopeChange} selectedSymbol={selectedSymbol} />
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

function ScopeToggle({
  scope,
  onScopeChange,
  selectedSymbol,
}: {
  scope: "current" | "all";
  onScopeChange: (s: "current" | "all") => void;
  selectedSymbol: string | null;
}) {
  return (
    <div className="flex items-stretch border border-hairline">
      <button
        type="button"
        onClick={() => onScopeChange("current")}
        disabled={!selectedSymbol}
        className={[
          "px-2 text-tiny uppercase tracking-label-up",
          scope === "current"
            ? "text-fg-primary bg-tier-2"
            : "text-fg-secondary hover:bg-tier-2",
          !selectedSymbol ? "opacity-50 cursor-not-allowed" : "",
        ].join(" ")}
      >
        {selectedSymbol ?? "—"}
      </button>
      <button
        type="button"
        onClick={() => onScopeChange("all")}
        className={[
          "px-2 text-tiny uppercase tracking-label-up border-l border-hairline",
          scope === "all"
            ? "text-fg-primary bg-tier-2"
            : "text-fg-secondary hover:bg-tier-2",
        ].join(" ")}
      >
        All
      </button>
    </div>
  );
}

function TradeRow({
  trade,
  active,
  isClosing,
  onSelect,
  onStartClose,
  onCancelClose,
  onClosed,
}: {
  trade: Trade;
  active: boolean;
  isClosing: boolean;
  onSelect: () => void;
  onStartClose: () => void;
  onCancelClose: () => void;
  onClosed: () => void;
}) {
  const dte = computeDte(trade);
  const isClosedRow = trade.status === "closed";
  const rowClass = active
    ? "border-t border-hairline bg-tier-2 cursor-pointer"
    : "border-t border-hairline hover:bg-tier-1 cursor-pointer";
  return (
    <>
      <tr
        className={rowClass}
        onClick={(e) => {
          // Don't toggle selection when the user clicked the inline
          // "close" action button or any of its inputs.
          const target = e.target as HTMLElement;
          if (target.closest("button, input")) return;
          onSelect();
        }}
        role="button"
        aria-pressed={active}
      >
        <Td className={`text-left ${active ? "border-l-2 border-amber pl-1.5" : ""} text-fg-primary`}>
          {trade.symbol}
        </Td>
        <Td className="text-left text-fg-primary">
          {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
        </Td>
        <Td className="text-right text-fg-secondary">{formatDate(trade.entry_date)}</Td>
        <Td className="text-right text-fg-secondary">{dte == null ? "—" : `${dte}d`}</Td>
        <Td className={`text-right ${trade.net_debit_credit < 0 ? "text-bullish" : "text-fg-primary"}`}>
          {formatNet(trade.net_debit_credit)}
        </Td>
        <Td className={`text-right ${pnlClass(trade.realized_pnl)}`}>
          {trade.realized_pnl == null ? "—" : formatNet(trade.realized_pnl)}
        </Td>
        <Td className="text-left">
          <StatusChip status={trade.status} />
        </Td>
        <Td className="text-left">
          <PaperChip isPaper={trade.is_paper} />
        </Td>
        <Td className="text-right">
          {!isClosedRow && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                isClosing ? onCancelClose() : onStartClose();
              }}
              className="text-tiny text-fg-tertiary hover:text-amber px-1"
            >
              {isClosing ? "cancel" : "close"}
            </button>
          )}
        </Td>
      </tr>
      {isClosing && (
        <CloseForm trade={trade} onClosed={onClosed} onCancel={onCancelClose} />
      )}
    </>
  );
}

function CloseForm({
  trade,
  onClosed,
  onCancel,
}: {
  trade: Trade;
  onClosed: () => void;
  onCancel: () => void;
}) {
  const updateTrade = useUpdateTrade();
  const [exitPrice, setExitPrice] = useState("");
  const [pnl, setPnl] = useState("");

  const submit = async () => {
    if (!exitPrice) return;
    await updateTrade.mutateAsync({
      id: trade.id,
      patch: {
        status: "closed",
        exit_date: new Date().toISOString(),
        exit_underlying_price: Number(exitPrice),
        realized_pnl: pnl ? Number(pnl) : 0,
      },
    });
    onClosed();
  };

  return (
    <tr className="bg-tier-1 border-t border-hairline">
      <td colSpan={9} className="px-3 py-2">
        <div className="flex items-center gap-3 text-tiny">
          <span className="text-fg-secondary uppercase tracking-label-up">
            Close {trade.symbol}
          </span>
          <label className="flex items-center gap-1">
            <span className="text-fg-tertiary">Exit price</span>
            <input
              type="number"
              step="0.01"
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="h-6 w-20 px-1 font-mono tabular-nums bg-tier-0 border border-hairline text-fg-primary text-right"
              style={{ borderRadius: 0 }}
            />
          </label>
          <label className="flex items-center gap-1">
            <span className="text-fg-tertiary">Realized P&amp;L</span>
            <input
              type="number"
              step="0.01"
              value={pnl}
              onChange={(e) => setPnl(e.target.value)}
              placeholder="0"
              className="h-6 w-24 px-1 font-mono tabular-nums bg-tier-0 border border-hairline text-fg-primary text-right placeholder:text-fg-tertiary"
              style={{ borderRadius: 0 }}
            />
          </label>
          <button
            type="button"
            onClick={submit}
            disabled={updateTrade.isPending || !exitPrice}
            className="h-6 px-2 uppercase tracking-label-up border border-amber text-amber hover:bg-tier-2 disabled:opacity-50"
            style={{ borderRadius: 0 }}
          >
            Save close
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="h-6 px-2 text-fg-tertiary hover:text-fg-primary"
          >
            cancel
          </button>
        </div>
      </td>
    </tr>
  );
}

function StatusChip({ status }: { status: Trade["status"] }) {
  if (status === "open") {
    return <span className="text-fg-primary">OPEN</span>;
  }
  return <span className="text-fg-tertiary">CLOSED</span>;
}

function PaperChip({ isPaper }: { isPaper: boolean }) {
  if (isPaper) {
    return (
      <span className="border-l-2 border-cyan pl-1.5 text-cyan uppercase tracking-label-up">
        Paper
      </span>
    );
  }
  return (
    <span className="border-l-2 border-amber pl-1.5 text-amber uppercase tracking-label-up">
      Live
    </span>
  );
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th
      className={`px-2 py-1 font-normal text-tiny tracking-label-up ${className ?? ""}`}
    >
      {children}
    </th>
  );
}

function Td({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <td className={`px-2 py-1 ${className ?? ""}`}>{children}</td>;
}

function computeDte(trade: Trade): number | null {
  if (trade.legs.length === 0) return null;
  // Use the nearest expiry across legs — that's typically when the
  // position needs to be managed.
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let nearest: number | null = null;
  for (const leg of trade.legs) {
    const exp = new Date(leg.expiry + "T00:00:00");
    const diff = Math.round((exp.getTime() - today.getTime()) / 86_400_000);
    if (nearest == null || diff < nearest) nearest = diff;
  }
  return nearest;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function formatNet(value: number): string {
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function pnlClass(pnl: number | null | undefined): string {
  if (pnl == null) return "text-fg-tertiary";
  if (pnl > 0) return "text-bullish";
  if (pnl < 0) return "text-bearish";
  return "text-fg-secondary";
}
