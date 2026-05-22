import { useCalendar } from "@/hooks/useCalendar";
import { useSelectedTicker } from "@/stores/selectedTicker";
import type { CalendarDay, CalendarEvent, EventType } from "@/types/calendar";

/**
 * 7-day forward calendar strip — Bloomberg archetype (commit 5).
 *
 * 60px hairline grid, columns separated by 1px vertical borders. Today's
 * column highlights with a 2px amber left rule + one elevation up (tier-1).
 * Event pills have NO background fill — just a 2px left rule in the
 * event-type accent color, with the label in plain FG PRIMARY.
 */
export function CalendarStrip() {
  const { data, isLoading, isError } = useCalendar();
  const selectedSymbol = useSelectedTicker((s) => s.symbol);

  if (isLoading) {
    return <CalendarStripSkeleton />;
  }
  if (isError || !data) {
    return (
      <div className="px-4 py-2 border-b border-hairline bg-tier-0 text-tiny text-bearish">
        Failed to load calendar
      </div>
    );
  }

  const speakerNote = data.notes?.fed_speakers;

  return (
    <div className="border-b border-hairline bg-tier-0">
      <div className="grid grid-cols-7">
        {data.days.map((day, i) => (
          <DayColumn
            key={day.date}
            day={day}
            selectedSymbol={selectedSymbol}
            isLast={i === data.days.length - 1}
          />
        ))}
      </div>
      {speakerNote && (
        <div className="px-3 py-1 text-tiny text-fg-tertiary">{speakerNote}</div>
      )}
    </div>
  );
}

interface ColProps {
  day: CalendarDay;
  selectedSymbol: string | null;
  isLast: boolean;
}

function DayColumn({ day, selectedSymbol, isLast }: ColProps) {
  const tickerHit =
    !!selectedSymbol && day.events.some((e) => e.ticker === selectedSymbol);

  // Today's column gets a 2px amber left rule + one elevation up. Other
  // columns get a 1px right hairline (except the last). Ticker-hit columns
  // tint up to tier-1 even when not today.
  const containerClasses = [
    "px-2 py-1 flex flex-col",
    day.is_today ? "bg-tier-1 border-l-2 border-amber" : "",
    !day.is_today && tickerHit ? "bg-tier-1" : "",
    !isLast ? "border-r border-hairline" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={containerClasses} style={{ minHeight: 52 }}>
      <DayHeader date={day.date} isToday={day.is_today} />
      <div className="flex flex-col gap-0.5 mt-1">
        {day.events.map((event, i) => (
          <EventPill key={`${day.date}:${i}`} event={event} dateISO={day.date} />
        ))}
      </div>
    </div>
  );
}

function DayHeader({ date, isToday }: { date: string; isToday: boolean }) {
  const d = new Date(`${date}T00:00:00`);
  const weekday = d.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase();
  const day = d.getDate();
  const weekdayClass = isToday ? "text-amber" : "text-fg-secondary";
  const dayClass = isToday ? "text-amber" : "text-fg-primary";
  return (
    <div className="flex items-baseline gap-1">
      <span className={`text-tiny uppercase tracking-label-up ${weekdayClass}`}>
        {weekday}
      </span>
      <span className={`text-xs2 tabular-nums ${dayClass}`}>{day}</span>
    </div>
  );
}

/**
 * Per-event-type left-rule color class. No backgrounds. Earnings = cyan,
 * FOMC/OPEX/economic-high = amber, fed-speak/low-importance = secondary,
 * OPEX uses dashed amber.
 */
const eventBorderClass: Record<EventType, string> = {
  earnings: "border-l-2 border-cyan",
  fomc: "border-l-2 border-amber",
  fomc_minutes: "border-l-2 border-amber",
  fed_speak: "border-l-2 border-fg-secondary",
  economic: "border-l-2 border-fg-secondary", // overridden for high-importance below
  opex: "border-l-2 border-dashed border-amber",
  quad_witching: "border-l-2 border-amber",
};

function EventPill({ event, dateISO }: { event: CalendarEvent; dateISO: string }) {
  // Economic releases get amber for high-importance, secondary otherwise.
  const borderClass =
    event.type === "economic" && event.importance === "high"
      ? "border-l-2 border-amber"
      : eventBorderClass[event.type as EventType] ?? "border-l-2 border-fg-secondary";

  // Quad-witching keeps the uppercase tracked treatment per DESIGN.md.
  const labelClass =
    event.type === "quad_witching"
      ? "text-xs2 uppercase tracking-label-up text-fg-primary truncate"
      : "text-xs2 text-fg-primary truncate";

  return (
    <span
      className={`inline-block pl-1.5 pr-1 py-px ${borderClass}`}
      title={buildEventTooltip(event, dateISO)}
    >
      <span className={labelClass}>{event.title}</span>
    </span>
  );
}

// Canonical full names for abbreviated economic release labels. Keeps the
// pill itself short while the tooltip explains what the user is looking at.
const ECONOMIC_FULL_NAMES: Record<string, string> = {
  CPI: "Consumer Price Index",
  PPI: "Producer Price Index",
  NFP: "Employment Situation (Nonfarm Payrolls)",
  GDP: "Gross Domestic Product",
  "Retail Sales": "Advance Monthly Sales for Retail and Food Services",
  "Jobless Claims": "Initial Unemployment Insurance Claims",
  "ISM Mfg": "ISM Manufacturing PMI",
  "ISM Svc": "ISM Services PMI",
};

function buildEventTooltip(event: CalendarEvent, dateISO: string): string {
  // "2026-05-20" → "Wednesday, May 20"
  const d = new Date(`${dateISO}T00:00:00`);
  const datePrefix = d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  switch (event.type) {
    case "earnings": {
      const parts = event.title.split(" ");
      const ticker = event.ticker ?? parts[0] ?? "";
      const slot = parts[parts.length - 1];
      const slotLabel =
        slot === "AMC"
          ? "after market close"
          : slot === "BMO"
          ? "before market open"
          : "timing TBD";
      return `${datePrefix}\n${ticker} earnings — reports ${slotLabel}`;
    }
    case "fomc": {
      const hasSEP = event.title.includes("SEP");
      const hasPowell = event.title.includes("Powell");
      const bits: string[] = ["FOMC meeting"];
      if (hasSEP) bits.push("Summary of Economic Projections");
      if (hasPowell) bits.push("Powell press conference");
      return `${datePrefix}\n${bits.join(" · ")}`;
    }
    case "fomc_minutes":
      return `${datePrefix}\nFOMC minutes released — full meeting transcript`;
    case "fed_speak":
      return `${datePrefix}\nFed speaker: ${event.title}`;
    case "economic": {
      const fullName = ECONOMIC_FULL_NAMES[event.title] ?? event.title;
      const importanceLabel =
        event.importance === "high"
          ? "high-importance release"
          : event.importance === "medium"
          ? "medium-importance release"
          : "release";
      return `${datePrefix}\n${fullName} — ${importanceLabel}`;
    }
    case "opex":
      return `${datePrefix}\nMonthly options expiration (third Friday)`;
    case "quad_witching":
      return `${datePrefix}\nQuad witching expiration — stock options + index options + stock futures + index futures all expire together`;
    default:
      return `${datePrefix}\n${event.title}`;
  }
}

/**
 * 7-column skeleton — hairline day-header blocks + 1-2 ghost event slots
 * per column. Static (no animation), matches the loaded 64px min-height
 * so no layout jump.
 */
function CalendarStripSkeleton() {
  return (
    <div className="border-b border-hairline bg-tier-0">
      <div className="grid grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className={`px-2 py-1 flex flex-col ${i < 6 ? "border-r border-hairline" : ""}`}
            style={{ minHeight: 52 }}
          >
            <div className="flex items-baseline gap-1">
              <div className="h-2 w-6 bg-tier-2" />
              <div className="h-2 w-3 bg-tier-2" />
            </div>
            <div className="flex flex-col gap-0.5 mt-1.5">
              <div className="flex items-center gap-1">
                <div className="h-3 w-px bg-fg-secondary" />
                <div className="h-2.5 w-3/4 bg-tier-2" />
              </div>
              <div className="flex items-center gap-1">
                <div className="h-3 w-px bg-fg-secondary" />
                <div className="h-2.5 w-1/2 bg-tier-2" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
