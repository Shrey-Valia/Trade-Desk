import { useState } from "react";

import { useJournalCalendar } from "@/hooks/useJournalCalendar";
import type { CalendarDay, CalendarMonth } from "@/types/calendar_journal";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

interface Props {
  isPaper?: boolean | null;
  onDayClick?: (day: CalendarDay) => void;
}

/**
 * Topstep-style monthly P&L calendar. The primary view of /journal.
 *
 * Each day cell shows realized P&L bucketed by exit_date with a faint
 * green / red wash. Weekly totals sit in a 7th column at the row's
 * end. Today's cell gets an amber ring. Click a populated day to lift
 * it as the active day (used by the parent to render a detail strip
 * below the grid).
 */
export function JournalCalendar({ isPaper, onDayClick }: Props) {
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
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {isError ? (
          <div className="text-tiny text-bearish px-2 py-4">Failed to load calendar</div>
        ) : !data ? (
          <div className="text-tiny text-fg-tertiary px-2 py-4">Loading…</div>
        ) : (
          <CalendarGrid
            month={data}
            activeDate={activeDate}
            onDayClick={handleDayClick}
          />
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
              style={{ letterSpacing: "0.08em" }}>
          {month?.label ?? "—"}
        </span>
        {loading && <span className="text-tiny text-fg-tertiary">refreshing…</span>}
      </div>
      <div className="flex items-baseline gap-3 tabular-nums">
        <span className="text-tiny uppercase tracking-label-up text-fg-tertiary"
              style={{ fontSize: 9 }}>
          Month
        </span>
        <span
          className={`text-display font-medium ${pnlClass(month?.realized_pnl ?? 0)}`}
        >
          {month ? formatDollar(month.realized_pnl) : "—"}
        </span>
        <span className="text-tiny text-fg-tertiary">
          {month ? `${month.trade_count} trade${month.trade_count === 1 ? "" : "s"}` : ""}
        </span>
      </div>
    </header>
  );
}

function CalendarGrid({
  month,
  activeDate,
  onDayClick,
}: {
  month: CalendarMonth;
  activeDate: string | null;
  onDayClick: (day: CalendarDay) => void;
}) {
  return (
    <div className="border border-hairline">
      {/* Weekday header */}
      <div className="grid border-b border-hairline"
           style={{ gridTemplateColumns: "repeat(7, 1fr) 96px" }}>
        {WEEKDAYS.map((wd) => (
          <div
            key={wd}
            className="px-2 py-1.5 text-tiny uppercase tracking-label-up text-fg-tertiary border-r border-hairline last:border-r-0"
            style={{ fontSize: 9 }}
          >
            {wd}
          </div>
        ))}
        <div
          className="px-2 py-1.5 text-tiny uppercase tracking-label-up text-fg-tertiary bg-tier-1"
          style={{ fontSize: 9 }}
        >
          Week
        </div>
      </div>
      {/* Weeks */}
      {month.weeks.map((w) => (
        <div
          key={w.week_of_month}
          className="grid border-b border-hairline last:border-b-0"
          style={{ gridTemplateColumns: "repeat(7, 1fr) 96px" }}
        >
          {w.days.map((d) => (
            <DayCell
              key={d.date}
              day={d}
              active={d.date === activeDate}
              onClick={() => onDayClick(d)}
            />
          ))}
          <WeekTotalCell week={w} />
        </div>
      ))}
    </div>
  );
}

function DayCell({
  day,
  active,
  onClick,
}: {
  day: CalendarDay;
  active: boolean;
  onClick: () => void;
}) {
  const dayNum = parseInt(day.date.slice(8, 10), 10);
  const hasPnl = day.trade_count > 0;
  const positive = day.realized_pnl > 0;
  const negative = day.realized_pnl < 0;

  // Faint tint — opacity-driven so it reads as a "wash" not a saturated fill.
  const tint = positive
    ? "bg-bullish/[0.07]"
    : negative
    ? "bg-bearish/[0.07]"
    : "";
  const muted = !day.in_month ? "opacity-40" : "";

  // Today's amber ring lives on top of the tint without changing it —
  // a 2px left rule mirrors the rest of the app's active-state idiom.
  const todayRule = day.is_today ? "border-l-2 border-amber" : "border-r border-hairline";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!hasPnl && !day.in_month}
      className={[
        "relative flex flex-col items-stretch justify-between text-left",
        "min-h-[88px] px-2 py-1.5",
        tint,
        muted,
        todayRule,
        active ? "ring-2 ring-amber ring-inset" : "",
        hasPnl ? "cursor-pointer hover:bg-tier-2" : "cursor-default",
        "border-b-0",
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
            "text-tiny tabular-nums",
            day.is_today
              ? "text-amber"
              : day.in_month
              ? "text-fg-secondary"
              : "text-fg-tertiary",
          ].join(" ")}
          style={{ fontSize: 10 }}
        >
          {dayNum}
        </span>
        {hasPnl && (
          <span className="text-tiny tabular-nums text-fg-tertiary" style={{ fontSize: 9 }}>
            {day.trade_count}t
          </span>
        )}
      </div>
      {hasPnl && (
        <div className="flex flex-col items-start gap-px">
          <span className={`text-medium font-medium tabular-nums ${pnlClass(day.realized_pnl)}`}>
            {formatDollarCompact(day.realized_pnl)}
          </span>
        </div>
      )}
    </button>
  );
}

function WeekTotalCell({ week }: { week: import("@/types/calendar_journal").CalendarWeek }) {
  const hasActivity = week.trade_count > 0;
  return (
    <div
      className={[
        "flex flex-col justify-between items-stretch px-2 py-1.5 bg-tier-1",
        "min-h-[88px]",
      ].join(" ")}
    >
      <span className="text-tiny uppercase tracking-label-up text-fg-tertiary"
            style={{ fontSize: 9 }}>
        Wk {week.week_of_month}
      </span>
      {hasActivity ? (
        <div className="flex flex-col items-start">
          <span className={`text-xs2 font-medium tabular-nums ${pnlClass(week.realized_pnl)}`}>
            {formatDollarCompact(week.realized_pnl)}
          </span>
          <span className="text-tiny text-fg-tertiary" style={{ fontSize: 9 }}>
            {week.trade_count}t
          </span>
        </div>
      ) : (
        <span className="text-tiny text-fg-tertiary" style={{ fontSize: 9 }}>—</span>
      )}
    </div>
  );
}

// -- helpers ------------------------------------------------------------------

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(cursor: string, delta: number): string {
  const [y, m] = cursor.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function formatDollar(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDollarCompact(value: number): string {
  // Compact cell-sized format. Drops cents for round-dollar values,
  // shows a $-prefix sign so the eye sees "$X" not "$-X".
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
