import { useState } from "react";

import { useJournalCalendar } from "@/hooks/useJournalCalendar";
import type { CalendarDay, CalendarMonth, CalendarWeek } from "@/types/calendar_journal";
import type { Trade } from "@/types/journal";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

interface Props {
  isPaper?: boolean | null;
  /** Loaded closed trades, keyed by id — drives win/loss pips and the
   *  has-journal tag-dot without a second fetch. */
  tradesById: Map<number, Trade>;
  onDayClick?: (day: CalendarDay) => void;
}

/**
 * Topstep-style monthly P&L calendar — the primary view of /journal.
 *
 * Restyled to the Trade Desk design kit (ui_kits/journal): a weekday-only
 * Mon–Fri grid with a weekly-total column, per-day win/loss pips and a
 * tag-dot when any of the day's trades carry a note or tags. Each day
 * cell carries a faint P&L wash + a colored left rule; today is amber.
 * Click a populated day to open the day-detail modal.
 */
export function JournalCalendar({ isPaper, tradesById, onDayClick }: Props) {
  const [monthCursor, setMonthCursor] = useState<string>(currentMonth());
  const [activeDate, setActiveDate] = useState<string | null>(null);
  const { data, isFetching, isError } = useJournalCalendar(monthCursor, isPaper);

  const handleDayClick = (day: CalendarDay) => {
    if (day.trade_count === 0) return;
    setActiveDate(day.date === activeDate ? null : day.date);
    onDayClick?.(day);
  };

  return (
    <section className="flex flex-col h-full min-h-0 bg-tier-0">
      <CalendarHeader
        monthCursor={monthCursor}
        onCursorChange={(m) => {
          setMonthCursor(m);
          setActiveDate(null);
        }}
        month={data}
        loading={isFetching}
      />
      <div className="flex-1 min-h-0 overflow-y-auto p-3.5 flex flex-col">
        {isError ? (
          <div className="text-tiny text-bearish px-2 py-4">Failed to load calendar</div>
        ) : !data ? (
          <div className="text-tiny text-fg-tertiary px-2 py-4">Loading…</div>
        ) : (
          <>
            <CalendarGrid
              month={data}
              tradesById={tradesById}
              activeDate={activeDate}
              onDayClick={handleDayClick}
            />
            <CalendarFooter month={data} tradesById={tradesById} />
          </>
        )}
      </div>
    </section>
  );
}

function CalendarHeader({
  monthCursor,
  onCursorChange,
  month,
  loading,
}: {
  monthCursor: string;
  onCursorChange: (m: string) => void;
  month: CalendarMonth | undefined;
  loading: boolean;
}) {
  return (
    <header className="flex items-center justify-between px-4 py-3 border-b border-hairline bg-tier-0 shrink-0">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onCursorChange(shiftMonth(monthCursor, -1))}
          className="h-7 w-7 flex items-center justify-center border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
          style={{ borderRadius: 0 }}
          aria-label="Previous month"
          title="Previous month"
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => onCursorChange(currentMonth())}
          className="h-7 px-2 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
          style={{ borderRadius: 0 }}
        >
          Today
        </button>
        <button
          type="button"
          onClick={() => onCursorChange(shiftMonth(monthCursor, +1))}
          className="h-7 w-7 flex items-center justify-center border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
          style={{ borderRadius: 0 }}
          aria-label="Next month"
          title="Next month"
        >
          ›
        </button>
        <span className="ml-2 text-medium uppercase tracking-label-up text-fg-primary"
              style={{ letterSpacing: "0.06em" }}>
          {month?.label ?? "—"}
        </span>
        {loading && <span className="text-tiny text-fg-tertiary">refreshing…</span>}
      </div>
      <div className="flex items-baseline gap-3 tabular-nums">
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 11 }}>
          Month
        </span>
        <span
          className={`text-display font-medium ${pnlClass(month?.realized_pnl ?? 0)}`}
        >
          {month ? formatDollarSigned(month.realized_pnl) : "—"}
        </span>
        <span className="text-tiny text-fg-tertiary">
          {month ? `${month.trade_count} trade${month.trade_count === 1 ? "" : "s"}` : ""}
        </span>
      </div>
    </header>
  );
}

const GRID_TEMPLATE = "repeat(5, minmax(0, 1fr)) 108px";

function CalendarGrid({
  month,
  tradesById,
  activeDate,
  onDayClick,
}: {
  month: CalendarMonth;
  tradesById: Map<number, Trade>;
  activeDate: string | null;
  onDayClick: (day: CalendarDay) => void;
}) {
  // Keep only Mon–Fri cells, and drop fully out-of-month leading/trailing
  // weeks so the grid doesn't carry an empty row at top or bottom.
  const weeks = month.weeks
    .map((w) => ({ week: w, days: w.days.filter((d) => isWeekday(d.date)) }))
    .filter((w) => w.days.some((d) => d.in_month));

  return (
    <div className="overflow-x-auto flex-1 min-h-0 flex flex-col">
    <div className="border border-hairline min-w-[660px] md:min-w-0 flex-1 min-h-0 flex flex-col">
      {/* Weekday header */}
      <div className="grid border-b border-hairline" style={{ gridTemplateColumns: GRID_TEMPLATE }}>
        {WEEKDAYS.map((wd) => (
          <div
            key={wd}
            className="px-2 py-1.5 text-tiny uppercase tracking-label-up text-fg-tertiary border-r border-hairline"
            style={{ fontSize: 11 }}
          >
            {wd}
          </div>
        ))}
        <div
          className="px-2 py-1.5 text-tiny uppercase tracking-label-up text-fg-tertiary-2 bg-tier-1"
          style={{ fontSize: 11 }}
        >
          Week
        </div>
      </div>
      {/* Weeks */}
      {weeks.map(({ week, days }) => (
        <div
          key={week.week_of_month}
          className="grid border-b border-hairline last:border-b-0 flex-1 min-h-0"
          style={{ gridTemplateColumns: GRID_TEMPLATE }}
        >
          {days.map((d) => (
            <DayCell
              key={d.date}
              day={d}
              tradesById={tradesById}
              active={d.date === activeDate}
              onClick={() => onDayClick(d)}
            />
          ))}
          <WeekTotalCell week={week} />
        </div>
      ))}
    </div>
    </div>
  );
}

function DayCell({
  day,
  tradesById,
  active,
  onClick,
}: {
  day: CalendarDay;
  tradesById: Map<number, Trade>;
  active: boolean;
  onClick: () => void;
}) {
  const dayNum = parseInt(day.date.slice(8, 10), 10);
  const hasPnl = day.trade_count > 0;
  const positive = day.realized_pnl > 0;
  const negative = day.realized_pnl < 0;
  const dayTrades = day.trade_ids.map((id) => tradesById.get(id)).filter(Boolean) as Trade[];
  const hasJournal = dayTrades.some(
    (t) => t.notes || t.review_note || t.tags.length > 0 || t.mistake_tags.length > 0,
  );

  // Faint wash + a colored left rule, mirroring the design kit. Today's
  // amber lives on the date label so it reads even on washed cells.
  const tint = positive
    ? "bg-bullish/[0.06]"
    : negative
    ? "bg-bearish/[0.06]"
    : "";
  const leftRule = positive
    ? "border-l-2 border-bullish"
    : negative
    ? "border-l-2 border-bearish"
    : "border-l-2 border-transparent";
  const muted = !day.in_month ? "opacity-40" : "";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!hasPnl}
      className={[
        "relative flex flex-col items-stretch justify-between text-left h-full",
        "min-h-[84px] px-2 py-1.5 border-r border-b-0 border-hairline",
        leftRule,
        tint,
        muted,
        active ? "ring-2 ring-amber ring-inset" : "",
        hasPnl ? "cursor-pointer hover:bg-tier-2" : "cursor-default",
      ].join(" ")}
      style={{ borderRadius: 0 }}
      aria-label={
        hasPnl
          ? `${day.date}: ${day.trade_count} trade(s), realized ${day.realized_pnl}`
          : day.date
      }
    >
      <div className="flex items-baseline justify-between">
        <span
          className={[
            "tabular-nums",
            day.is_today ? "text-fg-primary font-medium" : day.in_month ? "text-fg-tertiary-2" : "text-fg-tertiary",
          ].join(" ")}
          style={{ fontSize: 11 }}
        >
          {dayNum}
          {day.is_today && <span style={{ fontSize: 11, letterSpacing: "0.06em" }}> · today</span>}
        </span>
        {hasJournal && (
          <span
            className="bg-fg-tertiary"
            style={{ width: 5, height: 5, borderRadius: "50%" }}
            title="has notes / tags"
          />
        )}
      </div>
      {hasPnl && (
        <>
          <span className={`text-large font-medium tabular-nums ${pnlClass(day.realized_pnl)}`}>
            {formatDollarCompact(day.realized_pnl)}
          </span>
          <span className="flex items-center gap-1.5 text-fg-tertiary-2 tabular-nums" style={{ fontSize: 11 }}>
            <span className="inline-flex gap-0.5">
              {dayTrades.map((t) => (
                <span
                  key={t.id}
                  className={(t.realized_pnl ?? 0) >= 0 ? "bg-bullish" : "bg-bearish"}
                  style={{ width: 5, height: 5, borderRadius: "50%" }}
                />
              ))}
            </span>
            {day.trade_count} trade{day.trade_count === 1 ? "" : "s"}
          </span>
        </>
      )}
    </button>
  );
}

function WeekTotalCell({ week }: { week: CalendarWeek }) {
  const hasActivity = week.trade_count > 0;
  return (
    <div className="flex flex-col justify-center gap-0.5 px-2.5 py-1.5 bg-tier-1 min-h-[84px] h-full">
      <span className="uppercase tracking-label-up text-fg-tertiary" style={{ fontSize: 11 }}>
        Wk {week.week_of_month}
      </span>
      {hasActivity ? (
        <>
          <span className={`text-medium font-medium tabular-nums ${pnlClass(week.realized_pnl)}`}>
            {formatDollarCompact(week.realized_pnl)}
          </span>
          <span className="text-fg-tertiary-2 tabular-nums" style={{ fontSize: 11 }}>
            {week.trade_count} trade{week.trade_count === 1 ? "" : "s"}
          </span>
        </>
      ) : (
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>—</span>
      )}
    </div>
  );
}

function CalendarFooter({
  month,
  tradesById,
}: {
  month: CalendarMonth;
  tradesById: Map<number, Trade>;
}) {
  // Win rate + green days over in-month, weekday cells only.
  let wins = 0;
  let total = 0;
  let greenDays = 0;
  for (const week of month.weeks) {
    for (const d of week.days) {
      if (!d.in_month || !isWeekday(d.date) || d.trade_count === 0) continue;
      if (d.realized_pnl > 0) greenDays += 1;
      for (const id of d.trade_ids) {
        const t = tradesById.get(id);
        if (!t || t.realized_pnl == null) continue;
        total += 1;
        if (t.realized_pnl >= 0) wins += 1;
      }
    }
  }
  const winRate = total ? Math.round((wins / total) * 100) : null;

  return (
    <div className="flex items-center gap-6 px-1 pt-3 tabular-nums">
      <FootItem
        label="Month net"
        value={formatDollarSigned(month.realized_pnl)}
        tone={month.realized_pnl >= 0 ? "bull" : "bear"}
      />
      <FootItem label="Trades" value={String(month.trade_count)} />
      <FootItem label="Win rate" value={winRate == null ? "—" : `${winRate}%`} />
      <FootItem label="Green days" value={String(greenDays)} tone="bull" />
      <span className="ml-auto text-tiny text-fg-tertiary">
        Click any day with trades to review its fills, notes &amp; tags →
      </span>
    </div>
  );
}

function FootItem({ label, value, tone }: { label: string; value: string; tone?: "bull" | "bear" }) {
  const toneCls =
    tone === "bull" ? "text-bullish" : tone === "bear" ? "text-bearish" : "text-fg-primary";
  // A zero green-day count shouldn't read as a positive signal.
  const cls = value === "0" && tone === "bull" ? "text-fg-primary" : toneCls;
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`text-xs2 font-medium ${cls}`}>{value}</span>
    </div>
  );
}

// -- helpers ------------------------------------------------------------------

function isWeekday(iso: string): boolean {
  const dow = new Date(`${iso}T12:00:00Z`).getUTCDay(); // 0 Sun .. 6 Sat
  return dow >= 1 && dow <= 5;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(cursor: string, delta: number): string {
  const [y, m] = cursor.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function formatDollarSigned(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDollarCompact(value: number): string {
  // Compact cell-sized format. Drops cents for round-dollar values,
  // shows a signed $-prefix so the eye sees "+$X" / "−$X".
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "+";
  const abs = Math.abs(value);
  if (abs === 0) return "$0";
  return `${sign}$${abs.toFixed(abs >= 100 ? 0 : 2)}`;
}

function pnlClass(v: number): string {
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}
