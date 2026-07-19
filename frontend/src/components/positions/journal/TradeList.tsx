import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { useUpdateTrade } from "@/hooks/useTrades";
import { useActivePosition } from "@/stores/activePosition";
import { useSelectedTicker } from "@/stores/selectedTicker";
import {
  MISTAKE_TAG_VOCABULARY,
  STRATEGY_LABELS,
  type Trade,
} from "@/types/journal";

interface Props {
  trades: Trade[];
  scope: "current" | "all";
  onScopeChange: (s: "current" | "all") => void;
  selectedSymbol: string | null;
  onAddTrade: () => void;
  /** Trades query failed — render a retry state instead of the
   * misleading "No trades logged yet" empty state. */
  loadFailed?: boolean;
  onRetry?: () => void;
}

/** Above this many trades the body is windowed (only on-screen rows mount).
 *  Below it the list renders plainly so short journals are byte-for-byte
 *  unchanged — virtualization is a pure perf optimization for long lists. */
const VIRTUALIZE_THRESHOLD = 30;

/** Collapsed-row height estimate (px) used to size the virtual window before
 *  rows are measured. Each row gets re-measured via measureElement so an
 *  expanded inline close-form (a taller row group) still windows correctly. */
const ESTIMATED_ROW_HEIGHT = 29;

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
  loadFailed = false,
  onRetry,
}: Props) {
  const [closingId, setClosingId] = useState<number | null>(null);
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const toggleActive = useActivePosition((s) => s.toggle);
  const setSelectedSymbol = useSelectedTicker((s) => s.setSymbol);
  const scrollRef = useRef<HTMLDivElement>(null);

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
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        {loadFailed ? (
          <div className="px-3 py-6 text-tiny text-center flex flex-col items-center gap-2">
            <span className="text-bearish">Couldn&rsquo;t load trades.</span>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="h-6 px-2 uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
                style={{ borderRadius: 0 }}
              >
                Retry
              </button>
            )}
          </div>
        ) : trades.length === 0 ? (
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
                <Th className="text-right">R</Th>
                <Th className="text-left">Status</Th>
                <Th className="text-left">Tag</Th>
                <Th />
              </tr>
            </thead>
            {trades.length > VIRTUALIZE_THRESHOLD ? (
              <VirtualBody
                trades={trades}
                scrollRef={scrollRef}
                activeTradeId={activeTradeId}
                closingId={closingId}
                onRowClick={onRowClick}
                setClosingId={setClosingId}
              />
            ) : (
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
            )}
          </table>
        )}
      </div>
    </div>
  );
}

/**
 * Windowed <tbody> for long journals. Only the rows in (and just around) the
 * viewport mount; the rest are accounted for with two spacer rows that hold
 * the scroll height. Row behavior is identical to the plain path — the same
 * <TradeRow> renders, so click-to-select, the inline close form, and the
 * working-order overlays all carry over unchanged. Heights are measured per
 * row (measureElement) so an expanded close form still scrolls correctly.
 */
function VirtualBody({
  trades,
  scrollRef,
  activeTradeId,
  closingId,
  onRowClick,
  setClosingId,
}: {
  trades: Trade[];
  scrollRef: React.RefObject<HTMLDivElement>;
  activeTradeId: number | null;
  closingId: number | null;
  onRowClick: (trade: Trade) => void;
  setClosingId: (id: number | null) => void;
}) {
  const virtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 8,
    // Stable identity so selection/close state survives reorders & the
    // viewport stays anchored to the same trade across data refreshes.
    getItemKey: (index) => trades[index].id,
  });

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();
  const paddingTop = items.length > 0 ? items[0].start : 0;
  const paddingBottom =
    items.length > 0 ? totalSize - items[items.length - 1].end : 0;

  return (
    <tbody>
      {paddingTop > 0 && (
        <tr aria-hidden>
          <td colSpan={10} style={{ height: paddingTop, padding: 0 }} />
        </tr>
      )}
      {items.map((vi) => {
        const t = trades[vi.index];
        return (
          <TradeRow
            key={vi.key}
            trade={t}
            dataIndex={vi.index}
            measureRef={virtualizer.measureElement}
            active={activeTradeId === t.id}
            isClosing={closingId === t.id}
            onSelect={() => onRowClick(t)}
            onStartClose={() => setClosingId(t.id)}
            onCancelClose={() => setClosingId(null)}
            onClosed={() => setClosingId(null)}
          />
        );
      })}
      {paddingBottom > 0 && (
        <tr aria-hidden>
          <td colSpan={10} style={{ height: paddingBottom, padding: 0 }} />
        </tr>
      )}
    </tbody>
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
  measureRef,
  dataIndex,
}: {
  trade: Trade;
  active: boolean;
  isClosing: boolean;
  onSelect: () => void;
  onStartClose: () => void;
  onCancelClose: () => void;
  onClosed: () => void;
  /** Virtualized path only: attaches the virtualizer's resize observer to
   *  the primary row so dynamic heights re-measure. Omitted (plain render)
   *  for short lists, leaving the markup identical. */
  measureRef?: (el: HTMLElement | null) => void;
  dataIndex?: number;
}) {
  // DTE is a management number for OPEN positions; on closed rows it
  // just counts days since expiry (negative), which reads like a bug.
  const isClosedRow = trade.status === "closed";
  const dte = isClosedRow ? null : computeDte(trade);
  const rowClass = active
    ? "border-t border-hairline bg-tier-2 cursor-pointer"
    : "border-t border-hairline hover:bg-tier-1 cursor-pointer";
  return (
    <>
      <tr
        ref={measureRef}
        data-index={dataIndex}
        className={rowClass}
        onClick={(e) => {
          // Don't toggle selection when the user clicked the inline
          // "close" action button or any of its inputs.
          const target = e.target as HTMLElement;
          if (target.closest("button, input")) return;
          onSelect();
        }}
        onKeyDown={(e) => {
          // Keyboard-operable to match role="button": Enter/Space select the
          // row, with the same inner-control guard as onClick.
          if (e.key !== "Enter" && e.key !== " ") return;
          const target = e.target as HTMLElement;
          if (target.closest("button, input")) return;
          e.preventDefault();
          onSelect();
        }}
        tabIndex={0}
        role="button"
        aria-pressed={active}
      >
        <Td className={`text-left ${active ? "border-l-2 border-amber pl-1.5" : ""} text-fg-primary`}>
          <span className="inline-flex items-center gap-1.5">
            {trade.symbol}
            {trade.screenshot_url && <ScreenshotThumb url={trade.screenshot_url} />}
          </span>
        </Td>
        <Td className="text-left text-fg-primary">
          <span title={legFillsTitle(trade)}>
            {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
          </span>
        </Td>
        <Td className="text-right text-fg-secondary">{formatDate(trade.entry_date)}</Td>
        <Td className="text-right text-fg-secondary">{dte == null ? "—" : `${dte}d`}</Td>
        <Td className={`text-right ${trade.net_debit_credit < 0 ? "text-bullish" : "text-fg-primary"}`}>
          {formatNet(trade.net_debit_credit)}
        </Td>
        <Td className={`text-right ${pnlClass(trade.realized_pnl)}`}>
          {trade.realized_pnl == null ? "—" : formatNet(trade.realized_pnl)}
        </Td>
        <Td className={`text-right ${pnlClass(trade.r_multiple ?? null)}`}>
          {trade.r_multiple == null ? "—" : formatRMultiple(trade.r_multiple)}
        </Td>
        <Td className="text-left">
          <StatusChip status={trade.status} closeReason={trade.close_reason} />
        </Td>
        <Td className="text-left">
          <div className="flex items-center gap-1.5">
            <PaperChip isPaper={trade.is_paper} />
            {isCopiedTrade(trade) && <CopyBadge />}
          </div>
        </Td>
        <Td className="text-right">
          {!isClosedRow && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (isClosing) onCancelClose();
                else onStartClose();
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
  const [mistakes, setMistakes] = useState<string[]>([]);
  const [customMistake, setCustomMistake] = useState("");
  const [review, setReview] = useState("");

  const toggleMistake = (tag: string) => {
    setMistakes((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };
  const addCustom = () => {
    const t = customMistake.trim();
    if (!t || mistakes.includes(t)) {
      setCustomMistake("");
      return;
    }
    setMistakes([...mistakes, t]);
    setCustomMistake("");
  };

  const submit = async () => {
    if (!exitPrice) return;
    await updateTrade.mutateAsync({
      id: trade.id,
      patch: {
        status: "closed",
        exit_date: new Date().toISOString(),
        exit_underlying_price: Number(exitPrice),
        realized_pnl: pnl ? Number(pnl) : 0,
        mistake_tags: mistakes,
        review_note: review.trim() || undefined,
      },
    });
    onClosed();
  };

  return (
    <tr className="bg-tier-1 border-t border-hairline">
      <td colSpan={10} className="px-3 py-2">
        <div className="flex flex-col gap-2 text-tiny">
          <div className="flex items-center gap-3 flex-wrap">
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
          <div className="flex items-start gap-3 flex-wrap">
            <span className="text-fg-tertiary uppercase tracking-label-up mt-1 shrink-0"
                  style={{ fontSize: 11 }}>
              Mistakes
            </span>
            <div className="flex gap-1 flex-wrap">
              {MISTAKE_TAG_VOCABULARY.map((tag) => {
                const on = mistakes.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleMistake(tag)}
                    className={[
                      "px-1.5 py-px text-tiny border",
                      on
                        ? "border-amber text-amber bg-tier-2"
                        : "border-hairline text-fg-tertiary hover:bg-tier-2",
                    ].join(" ")}
                    style={{ borderRadius: 0, fontSize: 12 }}
                  >
                    {tag}
                  </button>
                );
              })}
              {/* Custom mistake input */}
              <input
                type="text"
                value={customMistake}
                onChange={(e) => setCustomMistake(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCustom();
                  }
                }}
                placeholder="+ custom"
                className="h-6 w-24 px-1 text-tiny bg-tier-0 border border-hairline text-fg-primary placeholder:text-fg-tertiary"
                style={{ borderRadius: 0, fontSize: 12 }}
              />
            </div>
          </div>
          {mistakes.filter((m) => !MISTAKE_TAG_VOCABULARY.includes(m as never)).length > 0 && (
            <div className="flex items-center gap-1 flex-wrap pl-12">
              <span className="text-fg-tertiary" style={{ fontSize: 11 }}>
                Custom:
              </span>
              {mistakes
                .filter((m) => !MISTAKE_TAG_VOCABULARY.includes(m as never))
                .map((m) => (
                  <span
                    key={m}
                    className="inline-flex items-center gap-1 px-1.5 py-px border border-amber text-amber"
                    style={{ borderRadius: 0, fontSize: 12 }}
                  >
                    {m}
                    <button
                      type="button"
                      onClick={() => toggleMistake(m)}
                      className="leading-none"
                      aria-label={`Remove ${m}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
            </div>
          )}
          <label className="flex items-start gap-3">
            <span className="text-fg-tertiary uppercase tracking-label-up mt-1 shrink-0"
                  style={{ fontSize: 11 }}>
              Review
            </span>
            <textarea
              value={review}
              onChange={(e) => setReview(e.target.value)}
              rows={2}
              placeholder="Post-trade note — what would you do differently?"
              className="flex-1 px-1 py-0.5 text-tiny bg-tier-0 border border-hairline text-fg-primary placeholder:text-fg-tertiary resize-none"
              style={{ borderRadius: 0 }}
            />
          </label>
        </div>
      </td>
    </tr>
  );
}

/** Small inline screenshot thumbnail. Clicking opens a full-size lightbox
 *  overlay; the click is stopped so it never toggles the row selection. */
function ScreenshotThumb({ url }: { url: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="inline-flex shrink-0 border border-hairline hover:border-amber"
        style={{ borderRadius: 0, padding: 0, lineHeight: 0 }}
        aria-label="View trade screenshot"
        title="View screenshot"
      >
        <img
          src={url}
          alt="trade screenshot"
          className="object-cover"
          style={{ width: 18, height: 18, display: "block" }}
        />
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Trade screenshot"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
          onClick={(e) => {
            e.stopPropagation();
            setOpen(false);
          }}
        >
          <img
            src={url}
            alt="trade screenshot"
            className="max-w-[90vw] max-h-[85vh] border border-hairline-strong"
            style={{ borderRadius: 0 }}
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}

function StatusChip({
  status,
  closeReason,
}: {
  status: Trade["status"];
  closeReason?: Trade["close_reason"];
}) {
  if (status === "open") {
    return <span className="text-fg-primary">OPEN</span>;
  }
  // Distinguish how a closed position was closed so cascaded copy closes
  // and forced auto-liquidations are legible at a glance.
  if (status === "closed" && closeReason === "liquidation") {
    return (
      <span
        className="text-bearish uppercase tracking-label-up"
        title="Auto-liquidated — closed by the risk engine on an MLL/DLL breach."
      >
        Liquidated
      </span>
    );
  }
  if (status === "closed" && closeReason === "expiry_closeout") {
    return (
      <span
        className="text-fg-tertiary"
        title="Closed by the expiration-day policy — 0DTE books are flattened shortly before the bell instead of riding into assignment/pin risk."
      >
        CLOSED
        <span className="text-amber" style={{ fontSize: 10 }}>
          {" "}
          · exp
        </span>
      </span>
    );
  }
  if (status === "closed" && closeReason === "limit") {
    return (
      <span
        className="text-fg-tertiary"
        title="Closed by a resting close-limit — filled at the trader's named price."
      >
        CLOSED
        <span className="text-amber" style={{ fontSize: 10 }}>
          {" "}
          · lmt
        </span>
      </span>
    );
  }
  if (status === "closed" && closeReason === "copy") {
    return (
      <span
        className="text-fg-tertiary"
        title="Closed by the lead account's copy cascade."
      >
        CLOSED
        <span className="text-cyan" style={{ fontSize: 10 }}>
          {" "}
          · copy
        </span>
      </span>
    );
  }
  if (status === "cancelled") {
    return <span className="text-fg-tertiary">CANCELLED</span>;
  }
  if (status === "working") {
    return <span className="text-amber uppercase tracking-label-up">Working</span>;
  }
  return <span className="text-fg-tertiary">CLOSED</span>;
}

/** Leg-level fill tape for the strategy cell's tooltip — the per-execution
 *  detail the compact row can't carry: every leg's entry fill, plus the
 *  exit context on closed rows. */
function legFillsTitle(trade: Trade): string {
  const legs = trade.legs
    .map(
      (l) =>
        `${l.action === "buy" ? "+" : "−"}${l.contracts ?? 1}× ${l.strike}` +
        `${l.side === "call" ? "C" : "P"} filled @ ${(l.entry_price ?? 0).toFixed(2)}`,
    )
    .join("\n");
  const exit =
    trade.status === "closed"
      ? `\nclosed${trade.close_reason ? ` (${trade.close_reason})` : ""}` +
        `${trade.exit_underlying_price != null ? ` · und $${trade.exit_underlying_price.toFixed(2)}` : ""}` +
        `${trade.realized_pnl != null ? ` · realized $${trade.realized_pnl.toFixed(2)}` : ""}`
      : "";
  return `Entry fills:\n${legs}${exit}`;
}

/** True when this row is a copy-traded mirror of a lead account's trade.
 *
 * The journal trade schema does not expose `copied_from_trade_id`, but
 * services/copy_trade tags every mirrored row with the "copy" tag (and a
 * "copied from <lead>" note) — so the tag is the reliable, schema-exposed
 * signal that a row is a follower copy. Closed copies additionally carry
 * close_reason="copy". */
function isCopiedTrade(trade: Trade): boolean {
  return (
    (trade.tags?.includes("copy") ?? false) || trade.close_reason === "copy"
  );
}

/** Small badge marking a follower-copied mirror trade in the journal. */
function CopyBadge() {
  return (
    <span
      className="border-l-2 border-cyan pl-1.5 text-cyan uppercase tracking-label-up"
      title="Copied from a lead account."
      style={{ fontSize: 11 }}
    >
      Copied
    </span>
  );
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
      scope="col"
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

function formatRMultiple(r: number): string {
  const sign = r < 0 ? "−" : r > 0 ? "+" : "";
  return `${sign}${Math.abs(r).toFixed(2)}R`;
}

function pnlClass(pnl: number | null | undefined): string {
  if (pnl == null) return "text-fg-tertiary";
  if (pnl > 0) return "text-bullish";
  if (pnl < 0) return "text-bearish";
  return "text-fg-secondary";
}
