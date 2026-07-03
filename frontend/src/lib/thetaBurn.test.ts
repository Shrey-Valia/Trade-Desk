import { describe, expect, it } from "vitest";

import {
  formatCountdown,
  hourlyThetaBurn,
  remainingSessionMs,
} from "@/lib/thetaBurn";

describe("hourlyThetaBurn", () => {
  it("compresses the per-day theta into the remaining session hours", () => {
    // −$42/day with 2h20m left → the rest of the day's decay lands before
    // the bell: −42 / (7/3) = −$18/hr.
    expect(hourlyThetaBurn(-42, 7 / 3)).toBeCloseTo(-18, 10);
  });

  it("keeps the sign — a net-credit (short) position COLLECTS theta", () => {
    expect(hourlyThetaBurn(65, 6.5)).toBeCloseTo(10, 10);
  });

  it("scales up as the session drains (same theta, less time)", () => {
    const early = hourlyThetaBurn(-42, 6.5)!;
    const late = hourlyThetaBurn(-42, 0.5)!;
    expect(Math.abs(late)).toBeGreaterThan(Math.abs(early));
    expect(late).toBeCloseTo(-84, 10);
  });

  it("returns null when the session is over (no negative hours)", () => {
    expect(hourlyThetaBurn(-42, 0)).toBeNull();
    expect(hourlyThetaBurn(-42, -1.25)).toBeNull();
  });

  it("returns null on non-finite input", () => {
    expect(hourlyThetaBurn(NaN, 2)).toBeNull();
    expect(hourlyThetaBurn(-42, Infinity)).toBeNull();
  });

  it("passes zero theta through as a zero rate", () => {
    expect(hourlyThetaBurn(0, 3)).toBe(0);
  });
});

describe("remainingSessionMs", () => {
  it("uses today_close from market status when present", () => {
    const now = Date.parse("2026-07-02T15:00:00Z");
    const close = "2026-07-02T20:00:00Z"; // 4pm ET in UTC (EDT)
    expect(remainingSessionMs(now, close)).toBe(5 * 3_600_000);
  });

  it("clamps at 0 after the close — never negative", () => {
    const now = Date.parse("2026-07-02T21:30:00Z");
    expect(remainingSessionMs(now, "2026-07-02T20:00:00Z")).toBe(0);
  });

  it("falls back to 4:00pm ET when today_close is missing/garbage", () => {
    // 2026-07-02 is EDT (UTC−4): 18:00Z = 2:00pm ET → 2h to the 4pm bell.
    const now = Date.parse("2026-07-02T18:00:00Z");
    expect(remainingSessionMs(now, null)).toBe(2 * 3_600_000);
    expect(remainingSessionMs(now, "not-a-date")).toBe(2 * 3_600_000);
  });
});

describe("formatCountdown", () => {
  it("renders H:MM", () => {
    expect(formatCountdown(2 * 3_600_000 + 5 * 60_000)).toBe("2:05");
    expect(formatCountdown(45 * 60_000)).toBe("0:45");
  });

  it("floors to the minute and clamps at 0:00", () => {
    expect(formatCountdown(59_000)).toBe("0:00");
    expect(formatCountdown(-5_000)).toBe("0:00");
  });
});
