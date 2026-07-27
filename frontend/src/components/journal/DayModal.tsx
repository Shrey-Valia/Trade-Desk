import { useState } from "react";

import { Modal } from "@/components/ui/Modal";
import { useUpdateTrade } from "@/hooks/useTrades";
import { colors } from "@/lib/design";
import { STRATEGY_LABELS, type Trade, type TradeLeg } from "@/types/journal";

interface Props {
  /** ISO date "YYYY-MM-DD" of the day being inspected. */
  date: string;
  /** Closed trades that exit on this day (already filtered by the parent). */
  trades: Trade[];
  onClose: () => void;
}

/**
 * Day-detail modal — the journal's learning surface.
 *
 * Replaces the old flat day strip. Each trade in the day is shown as a
 * header row + an always-expanded detail block: structure / legs, an
 * editable note, the trade's tags and mistake tags, and an honest
 * intratrade summary (entry → exit, hold, return, R).
 *
 * Matches ui_kits/journal (cal-modal / cal-tradehead / jn-detail) using
 * the app's own tokens. Entry greeks and a true intratrade P&L path are
 * deliberately omitted — neither is captured in the data model yet
 * (greeks would need a BS-at-entry compute; the path needs per-trade
 * snapshots). We show the net move rather than fabricating a curve.
 */
export function DayModal({ date, trades, onClose }: Props) {
  const net = trades.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);
  // Win = strictly positive P&L, matching the backend's win-rate
  // definition (journal_analytics) so this modal and ANALYTICS agree.
  const wins = trades.filter((t) => (t.realized_pnl ?? 0) > 0).length;
  const winRate = trades.length ? Math.round((wins / trades.length) * 100) : 0;

  return (
    <Modal
      open
      onClose={onClose}
      labelledBy="day-modal-title"
      panelClassName="flex flex-col overflow-hidden bg-tier-1 border border-hairline-strong w-[760px] max-w-full max-h-[88vh] rounded"
    >
      {/* head */}
      <header className="flex items-center gap-4 px-4 py-3 border-b border-hairline shrink-0">
        <span
          id="day-modal-title"
          className="text-medium font-medium text-fg-primary"
        >
          {formatLongDate(date)}
        </span>
          <span className="text-tiny uppercase tracking-label-up text-fg-tertiary">
            {formatWeekday(date)}
          </span>
          <div className="ml-auto flex items-stretch gap-4 tabular-nums">
            <Summary label="Trades" value={String(trades.length)} />
            <Summary label="Win rate" value={`${winRate}%`} />
            <Summary
              label="Day P&L"
              value={formatDollarSigned(net)}
              tone={net > 0 ? "bull" : net < 0 ? "bear" : undefined}
            />
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex items-center justify-center bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-amber"
            style={{ width: 26, height: 26, borderRadius: 4 }}
          >
            ✕
          </button>
        </header>

      {/* body */}
      <div className="overflow-y-auto min-h-0">
        {trades.map((t) => (
          <div key={t.id}>
            <TradeHead trade={t} />
            <TradeDetail trade={t} />
          </div>
        ))}
      </div>
    </Modal>
  );
}

function Summary({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bull" | "bear";
}) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-fg-tertiary-2 uppercase tracking-label-up" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`text-xs2 font-medium ${tone ? toneClass(tone) : "text-fg-primary"}`}>
        {value}
      </span>
    </div>
  );
}

// -- trade header row --------------------------------------------------------

function TradeHead({ trade }: { trade: Trade }) {
  const win = (trade.realized_pnl ?? 0) >= 0;
  return (
    <div
      className="grid items-center gap-2 px-4 py-2 bg-tier-2 border-b border-hairline"
      style={{
        gridTemplateColumns: "150px 1fr 120px 96px",
        borderLeft: `2px solid ${win ? "rgba(77,209,124,0.6)" : "rgba(232,92,92,0.6)"}`,
      }}
    >
      <div className="flex flex-col leading-tight">
        <span className="text-xs2 font-medium text-fg-primary">{trade.symbol}</span>
        <span className="text-fg-tertiary-2 uppercase" style={{ fontSize: 11, letterSpacing: "0.04em" }}>
          {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
        </span>
      </div>
      <span className="text-tiny text-fg-secondary truncate">{structSummary(trade.legs)}</span>
      <span className="text-xs2 text-fg-secondary text-right tabular-nums">
        {formatUnderlying(trade.entry_underlying_price)}
        <span className="text-fg-tertiary mx-1">→</span>
        {formatUnderlying(trade.exit_underlying_price ?? null)}
      </span>
      <span className={`text-right text-sm font-medium tabular-nums ${pnlClass(trade.realized_pnl ?? null)}`}>
        {trade.realized_pnl == null ? "—" : formatDollarSigned(trade.realized_pnl)}
      </span>
    </div>
  );
}

// -- expanded detail ---------------------------------------------------------

function TradeDetail({ trade }: { trade: Trade }) {
  const qty = trade.legs.reduce((sum, l) => sum + l.contracts, 0);
  const basis = trade.risk_amount && trade.risk_amount > 0
    ? trade.risk_amount
    : Math.abs(trade.net_debit_credit);
  const retPct = basis > 0 && trade.realized_pnl != null
    ? (trade.realized_pnl / basis) * 100
    : null;
  const hold = holdMinutes(trade.entry_date, trade.exit_date ?? null);

  return (
    <div
      className="grid gap-5 px-4 pt-4 pb-5 border-b border-hairline bg-tier-0"
      style={{ gridTemplateColumns: "1.1fr 1fr 1.2fr" }}
    >
      {/* structure */}
      <section>
        <SecHead>Structure · {qty} contract{qty === 1 ? "" : "s"}</SecHead>
        <div className="flex flex-col gap-1">
          {trade.legs.map((leg, i) => (
            <Row key={i} l={`leg ${i + 1}`} v={legLabel(leg)} />
          ))}
          <div className="mt-1.5">
            <Row
              l="entry → exit"
              v={`${formatUnderlying(trade.entry_underlying_price)} → ${formatUnderlying(trade.exit_underlying_price ?? null)}`}
            />
            <Row l="net debit / credit" v={formatDebitCredit(trade.net_debit_credit)} />
            <Row
              l="cost basis · risk"
              v={trade.risk_amount && trade.risk_amount > 0 ? formatDollar(trade.risk_amount) : "—"}
            />
          </div>
        </div>
      </section>

      {/* note + tags */}
      <section>
        <SecHead>Note</SecHead>
        <NoteEditor trade={trade} />
        <TagEditor trade={trade} />
        {trade.screenshot_url && <ScreenshotThumb url={trade.screenshot_url} />}
      </section>

      {/* intratrade — honest summary, not a fabricated path */}
      <section>
        <SecHead>Intratrade</SecHead>
        <div className="border border-hairline bg-tier-1 p-2" style={{ borderRadius: 4 }}>
          <div className="flex justify-between text-fg-tertiary-2 uppercase mb-1" style={{ fontSize: 11, letterSpacing: "0.06em" }}>
            <span>{formatTimeEt(trade.entry_date)}</span>
            <span className={pnlClass(trade.realized_pnl ?? null)}>
              {trade.realized_pnl == null ? "—" : formatDollarSigned(trade.realized_pnl)}
            </span>
            <span>{formatTimeEt(trade.exit_date ?? null)}</span>
          </div>
          <NetMoveLine pnl={trade.realized_pnl ?? 0} />
          <div className="text-fg-tertiary mt-1.5" style={{ fontSize: 11 }}>
            net move · intratrade path not recorded
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 mt-2.5">
          <Stat label="Hold time" value={hold == null ? "—" : formatHold(hold)} />
          <Stat
            label="Return · R"
            value={`${retPct == null ? "—" : formatPct(retPct)} · ${trade.r_multiple == null ? "—" : formatR(trade.r_multiple)}`}
          />
        </div>
      </section>
    </div>
  );
}

function NoteEditor({ trade }: { trade: Trade }) {
  const update = useUpdateTrade();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(trade.notes ?? "");

  const save = async () => {
    await update.mutateAsync({ id: trade.id, patch: { notes: draft.trim() } });
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1.5">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          autoFocus
          placeholder="Why you took it, what happened, what you'd repeat."
          className="text-tiny bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary p-2 resize-none"
          style={{ borderRadius: 4, lineHeight: 1.55 }}
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={save}
            disabled={update.isPending}
            className="h-6 px-2 text-tiny uppercase tracking-label-up border border-amber text-amber hover:bg-tier-2 disabled:opacity-50 rounded-btn"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(trade.notes ?? "");
              setEditing(false);
            }}
            className="text-tiny text-fg-tertiary hover:text-fg-primary"
          >
            cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className={[
        "block w-full text-left text-tiny border border-hairline bg-tier-1 p-2.5 hover:border-hairline-strong",
        trade.notes ? "text-fg-secondary" : "text-fg-tertiary",
      ].join(" ")}
      style={{ borderRadius: 4, minHeight: 56, lineHeight: 1.55 }}
    >
      {trade.notes ||
        "No note on this trade. Add one — why you took it, what happened, what you'd repeat."}
    </button>
  );
}

/** Self-applied intent tags are editable (add / remove → PATCH tags).
 *  Mistake tags are shown read-only — they're captured at close. */
function TagEditor({ trade }: { trade: Trade }) {
  const update = useUpdateTrade();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  const commit = async (next: string[]) => {
    await update.mutateAsync({ id: trade.id, patch: { tags: next } });
  };

  const addTag = async () => {
    const t = draft.trim();
    setDraft("");
    setAdding(false);
    if (!t || trade.tags.includes(t)) return;
    await commit([...trade.tags, t]);
  };

  const removeTag = async (tag: string) => {
    await commit(trade.tags.filter((x) => x !== tag));
  };

  return (
    <div className="flex flex-wrap gap-1.5 mt-2.5">
      {trade.tags.map((tag) => (
        <Tag key={`t-${tag}`} label={tag} kind={tagKind(tag)} onRemove={() => removeTag(tag)} />
      ))}
      {trade.mistake_tags.map((tag) => (
        <Tag key={`m-${tag}`} label={tag} kind="bad" />
      ))}
      {adding ? (
        <input
          autoFocus
          list="intent-tag-suggestions"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={addTag}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void addTag();
            } else if (e.key === "Escape") {
              setDraft("");
              setAdding(false);
            }
          }}
          placeholder="tag…"
          className="bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary uppercase"
          style={{ fontSize: 11, letterSpacing: "0.06em", padding: "2px 6px", borderRadius: 2, width: 90 }}
        />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="uppercase border border-dashed border-hairline text-fg-tertiary hover:text-amber hover:border-amber"
          style={{ fontSize: 11, letterSpacing: "0.06em", padding: "2px 7px", borderRadius: 2 }}
        >
          + tag
        </button>
      )}
      <datalist id="intent-tag-suggestions">
        {INTENT_TAG_SUGGESTIONS.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
    </div>
  );
}

const INTENT_TAG_SUGGESTIONS = [
  "planned",
  "good setup",
  "A+ setup",
  "discipline",
  "in plan",
] as const;

function Tag({
  label,
  kind,
  onRemove,
}: {
  label: string;
  kind: "good" | "bad" | "neutral";
  onRemove?: () => void;
}) {
  const cls =
    kind === "good"
      ? "text-bullish border-bullish"
      : kind === "bad"
      ? "text-bearish border-bearish"
      : "text-fg-tertiary-2 border-hairline-strong";
  return (
    <span
      className={`inline-flex items-center gap-1 uppercase border ${cls}`}
      style={{ fontSize: 11, letterSpacing: "0.06em", padding: "2px 7px", borderRadius: 2 }}
    >
      {label}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="leading-none hover:text-fg-primary"
          aria-label={`Remove ${label}`}
        >
          ×
        </button>
      )}
    </span>
  );
}

/** Two-point net-move indicator (0 → realized P&L). Deliberately a
 *  straight line — we know the endpoints, not the path. */
function NetMoveLine({ pnl }: { pnl: number }) {
  const win = pnl >= 0;
  const col = win ? colors.bullish : colors.bearish;
  // y=18 baseline; winner ends high (y=8), loser ends low (y=28).
  const endY = win ? 8 : 28;
  const startY = win ? 28 : 8;
  return (
    <svg width="100%" viewBox="0 0 200 36" preserveAspectRatio="none" style={{ display: "block", height: 36 }}>
      <line x1="0" y1="18" x2="200" y2="18" stroke={colors.borderHairline} strokeWidth="1" />
      <line
        x1="2"
        y1={pnl === 0 ? 18 : startY}
        x2="198"
        y2={pnl === 0 ? 18 : endY}
        stroke={pnl === 0 ? colors.borderHairline : col}
        strokeWidth="1.5"
      />
    </svg>
  );
}

/** Trade screenshot thumbnail for the day-detail. Click opens a full-size
 *  lightbox overlay. */
function ScreenshotThumb({ url }: { url: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block border border-hairline hover:border-amber"
        style={{ borderRadius: 0, padding: 0, lineHeight: 0 }}
        aria-label="View trade screenshot"
        title="View screenshot"
      >
        <img
          src={url}
          alt="trade screenshot"
          className="object-cover"
          style={{ width: 96, height: 60, display: "block" }}
        />
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Trade screenshot"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-6"
          onClick={() => setOpen(false)}
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
    </div>
  );
}

// -- small building blocks ---------------------------------------------------

function SecHead({ children }: { children: React.ReactNode }) {
  return (
    <div className="uppercase tracking-label-up text-fg-tertiary mb-2" style={{ fontSize: 11 }}>
      {children}
    </div>
  );
}

function Row({ l, v }: { l: string; v: string }) {
  return (
    <div className="flex justify-between text-tiny tabular-nums text-fg-secondary" style={{ fontSize: 11 }}>
      <span>{l}</span>
      <span className="text-fg-primary">{v}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-fg-tertiary-2 uppercase" style={{ fontSize: 11, letterSpacing: "0.06em" }}>
        {label}
      </span>
      <span className="text-xs2 text-fg-secondary tabular-nums">{value}</span>
    </div>
  );
}

// -- formatting --------------------------------------------------------------

function structSummary(legs: TradeLeg[]): string {
  return legs.map((l) => `${l.strike}${l.side === "call" ? "C" : "P"}`).join(" / ");
}

function legLabel(leg: TradeLeg): string {
  const oc = leg.side === "call" ? "C" : "P";
  return `${leg.action} ${leg.contracts}× ${leg.strike}${oc} @ $${leg.entry_price.toFixed(2)}`;
}

function tagKind(tag: string): "good" | "bad" | "neutral" {
  const t = tag.toLowerCase();
  if (/good|planned|a\+|disciplin/.test(t)) return "good";
  if (/revenge|fomo|broke|chased|oversiz|no exit|held too|cut winner|ignored|rolled too/.test(t)) return "bad";
  return "neutral";
}

function toneClass(tone: "bull" | "bear"): string {
  return tone === "bull" ? "text-bullish" : "text-bearish";
}

function pnlClass(v: number | null): string {
  if (v == null) return "text-fg-tertiary";
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}

function formatDollar(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDollarSigned(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDebitCredit(value: number): string {
  // Positive net = debit (paid); negative = credit (received).
  const label = value >= 0 ? "debit" : "credit";
  return `$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${label}`;
}

function formatUnderlying(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

function formatPct(p: number): string {
  const sign = p > 0 ? "+" : p < 0 ? "−" : "";
  return `${sign}${Math.abs(p).toFixed(0)}%`;
}

function formatR(r: number): string {
  const sign = r > 0 ? "+" : r < 0 ? "−" : "";
  return `${sign}${Math.abs(r).toFixed(2)}R`;
}

function formatHold(minutes: number): string {
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `${minutes}m`;
}

function holdMinutes(entryIso: string, exitIso: string | null): number | null {
  if (!exitIso) return null;
  const a = new Date(entryIso).getTime();
  const b = new Date(exitIso).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;
  return Math.round((b - a) / 60000);
}

function formatTimeEt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "America/New_York",
    });
  } catch {
    return "—";
  }
}

function formatLongDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatWeekday(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return d.toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
}
