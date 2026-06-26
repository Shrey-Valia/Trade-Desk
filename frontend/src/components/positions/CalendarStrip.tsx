import { useMemo } from "react";

import { useCalendar } from "@/hooks/useCalendar";
import type { CalendarDay, CalendarEvent, EventType } from "@/types/calendar";

/**
 * Econ-calendar strip — a compact horizontal pill row of the next few
 * trading days' market-moving events (FOMC / CPI / OPEX / earnings / ISM…).
 *
 * Consumes the previously-orphaned `useCalendar()` hook. Mounted in the
 * PositionsPage just above the chart so the trader sees what's on the
 * macro tape before placing a 0DTE position into an FOMC print.
 *
 * The backend already buckets events by trading day; here we flatten to a
 * single scrollable row ordered by date, each pill carrying its date label,
 * a short event label, and an importance-tinted accent. High-importance
 * events (FOMC, CPI, quad witching, earnings) read in amber; medium in cyan;
 * low in muted gray — the same color semantics used across the terminal.
 */
export function CalendarStrip() {
  const { data, isLoading, isError } = useCalendar();

  const pills = useMemo(() => (data ? flatten(data.days) : []), [data]);

  // Loading / error / empty states all collapse to a single thin row so the
  // chart never jumps as the (1h-cached) calendar resolves.
  if (isLoading) {
    return (
      <Strip>
        <span className="text-tiny text-fg-tertiary uppercase tracking-label-up">
          Loading calendar…
        </span>
      </Strip>
    );
  }
  if (isError) {
    return (
      <Strip>
        <span className="text-tiny text-fg-tertiary">Calendar unavailable.</span>
      </Strip>
    );
  }
  if (pills.length === 0) {
    return (
      <Strip>
        <span className="text-tiny text-fg-tertiary">
          No scheduled events in the next week.
        </span>
      </Strip>
    );
  }

  return (
    <Strip>
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0">
        Calendar
      </span>
      <div className="flex items-stretch gap-1.5 overflow-x-auto min-w-0">
        {pills.map((p, i) => (
          <Pill key={`${p.date}-${p.event.type}-${p.event.title}-${i}`} pill={p} />
        ))}
      </div>
    </Strip>
  );
}

interface FlatPill {
  date: string;
  isToday: boolean;
  event: CalendarEvent;
}

function flatten(days: CalendarDay[]): FlatPill[] {
  const out: FlatPill[] = [];
  for (const day of days) {
    for (const event of day.events) {
      out.push({ date: day.date, isToday: day.is_today, event });
    }
  }
  // Already date-ordered from the backend (sessions ascending); keep that.
  return out;
}

function Strip({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 px-3 h-7 shrink-0 bg-tier-1 border-b border-hairline">
      {children}
    </div>
  );
}

function Pill({ pill }: { pill: FlatPill }) {
  const tone = importanceTone(pill.event.importance);
  return (
    <span
      title={`${formatDate(pill.date)} · ${pill.event.title}`}
      className={[
        "inline-flex items-center gap-1.5 px-1.5 h-5 shrink-0 border bg-tier-0 tabular-nums",
        tone.border,
      ].join(" ")}
      style={{ borderRadius: 0, fontSize: 12 }}
    >
      <span
        className={[
          "uppercase tracking-label-up",
          pill.isToday ? "text-amber" : "text-fg-tertiary",
        ].join(" ")}
      >
        {pill.isToday ? "Today" : formatDate(pill.date)}
      </span>
      <span className={tone.text}>{eventGlyph(pill.event.type)}</span>
      <span className="text-fg-secondary truncate" style={{ maxWidth: 160 }}>
        {pill.event.title}
      </span>
    </span>
  );
}

function importanceTone(importance: CalendarEvent["importance"]): {
  border: string;
  text: string;
} {
  if (importance === "high") return { border: "border-amber", text: "text-amber" };
  if (importance === "medium") return { border: "border-cyan", text: "text-cyan" };
  return { border: "border-hairline", text: "text-fg-tertiary" };
}

/** Tiny leading marker per event family — keeps pills scannable at a glance
 * without a full icon set. */
function eventGlyph(type: EventType): string {
  switch (type) {
    case "earnings":
      return "ER";
    case "fomc":
      return "FOMC";
    case "fomc_minutes":
      return "MIN";
    case "fed_speak":
      return "FED";
    case "opex":
      return "OPEX";
    case "quad_witching":
      return "QUAD";
    case "economic":
      return "•";
    default:
      return "•";
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
