import { describe, expect, it } from "vitest";

import { inCurrentTradingDay, tradingDayStartMs } from "@/lib/tradingDay";

// 2026-07-18 (PDT, UTC−7): 5pm PT = 2026-07-19T00:00:00Z.
const SAT_6PM_PT = Date.parse("2026-07-19T01:00:00Z"); // 18:00 PT Jul 18
const SAT_NOON_PT = Date.parse("2026-07-18T19:00:00Z"); // 12:00 PT Jul 18

describe("tradingDayStartMs (5pm-PT accounting boundary)", () => {
  it("after 5pm PT the boundary is today's 5pm PT", () => {
    expect(tradingDayStartMs(SAT_6PM_PT)).toBe(
      Date.parse("2026-07-19T00:00:00Z"),
    );
  });

  it("before 5pm PT the boundary is YESTERDAY's 5pm PT", () => {
    expect(tradingDayStartMs(SAT_NOON_PT)).toBe(
      Date.parse("2026-07-18T00:00:00Z"),
    );
  });

  it("a UTC-calendar 'tomorrow' can still be the SAME trading day", () => {
    // 18:30 PT Jul 18 = 01:30Z Jul 19 — different UTC date, same trading day.
    const ts = "2026-07-19T01:30:00.000Z";
    expect(inCurrentTradingDay(ts, SAT_6PM_PT)).toBe(true);
  });

  it("this morning (before 5pm PT) is NOT in the post-5pm trading day", () => {
    expect(inCurrentTradingDay("2026-07-18T19:00:00Z", SAT_6PM_PT)).toBe(false);
  });

  it("null/garbage timestamps are never inside the window", () => {
    expect(inCurrentTradingDay(null, SAT_6PM_PT)).toBe(false);
    expect(inCurrentTradingDay("not-a-date", SAT_6PM_PT)).toBe(false);
  });
});
