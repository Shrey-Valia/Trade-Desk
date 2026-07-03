/**
 * Theta-burn clock math (0DTE-native) — pure helpers, unit-tested.
 *
 * A 0DTE option's quoted per-day theta IS (approximately) the remaining
 * time value: the contract dies at today's close, so the whole day's
 * decay lands inside the remaining session — not spread over 24 calendar
 * hours. The hourly burn therefore compresses the per-day theta into
 * the hours left before the bell.
 */

/**
 * $/hour decay rate: the per-day theta spread over the REMAINING session.
 *
 * Sign passes through untouched — a long (net-debit) position has negative
 * theta (paying decay); a short (net-credit) position has positive theta
 * (collecting it).
 *
 * Returns null when the session is over (remainingSessionHours <= 0) or
 * inputs are not finite — callers render the "session over" state instead
 * of a fake (or infinite) rate.
 */
export function hourlyThetaBurn(
  thetaPerDay: number,
  remainingSessionHours: number,
): number | null {
  if (!Number.isFinite(thetaPerDay) || !Number.isFinite(remainingSessionHours)) {
    return null;
  }
  if (remainingSessionHours <= 0) return null;
  return thetaPerDay / remainingSessionHours;
}

/**
 * Milliseconds until the session close, clamped at 0 (never negative).
 *
 * - `todayCloseIso` (market-status `today_close`, which also covers
 *   early-close half days) wins when it parses.
 * - Fallback: 4:00pm ET on the current day, derived from the ET wall
 *   clock so the caller needs no timezone math.
 */
export function remainingSessionMs(
  nowMs: number,
  todayCloseIso?: string | null,
): number {
  if (todayCloseIso) {
    const close = Date.parse(todayCloseIso);
    if (Number.isFinite(close)) return Math.max(0, close - nowMs);
  }
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).formatToParts(new Date(nowMs));
    const get = (t: string) =>
      Number(parts.find((p) => p.type === t)?.value ?? NaN);
    const h = get("hour");
    const m = get("minute");
    const s = get("second");
    if (![h, m, s].every(Number.isFinite)) return 0;
    const secsToClose = (16 * 60 - (h * 60 + m)) * 60 - s;
    return Math.max(0, secsToClose * 1000);
  } catch {
    return 0;
  }
}

/** "H:MM" countdown (floors to the minute; never negative). */
export function formatCountdown(ms: number): string {
  const totalMin = Math.max(0, Math.floor(ms / 60_000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}
