/**
 * The combine's accounting "trading day" boundary — 5:00pm America/Los_Angeles,
 * mirroring backend services/combine_settlement (DLL reset, RP&L window,
 * settlement). Display code that says "today" must use THIS window, not the
 * viewer's calendar day: the audit flagged two coexisting "today"s (UTC
 * calendar in widgets vs 5pm-PT in the money engine) as a reconciliation trap.
 */
export function tradingDayStartMs(nowMs: number = Date.now()): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(
    dtf.formatToParts(new Date(nowMs)).map((p) => [p.type, p.value]),
  ) as Record<string, string>;
  // PT wall-clock of "now", expressed as a UTC timestamp so arithmetic works.
  const ptWallNow = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour) % 24,
    Number(parts.minute),
    Number(parts.second),
  );
  const tzOffset = ptWallNow - nowMs; // −7h (PDT) / −8h (PST), in ms
  // Most recent 5pm PT wall-clock at/before now.
  let boundaryWall = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    17,
    0,
    0,
  );
  if (ptWallNow < boundaryWall) boundaryWall -= 24 * 3600 * 1000;
  return boundaryWall - tzOffset;
}

/** True when an ISO timestamp falls inside the CURRENT 5pm-PT trading day. */
export function inCurrentTradingDay(iso: string | null | undefined, nowMs?: number): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  return Number.isFinite(t) && t >= tradingDayStartMs(nowMs);
}
