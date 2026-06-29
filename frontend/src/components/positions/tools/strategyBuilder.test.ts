import { describe, expect, it } from "vitest";

import { presetLegs, strikeStep } from "./StrategyBuilder";

describe("strikeStep", () => {
  it("returns the median gap of a strike grid", () => {
    expect(strikeStep([95, 100, 105, 110])).toBe(5);
    expect(strikeStep([100, 100.5, 101, 101.5])).toBe(0.5);
  });
  it("falls back to 1 for a degenerate grid", () => {
    expect(strikeStep([])).toBe(1);
    expect(strikeStep([100])).toBe(1);
  });
});

describe("presetLegs (WS5 builder presets)", () => {
  it("vertical = long ATM call + short OTM call", () => {
    const legs = presetLegs("vertical", 100, 5);
    expect(legs).toHaveLength(2);
    expect(legs[0]).toMatchObject({ side: "call", action: "buy", strike: 100 });
    expect(legs[1]).toMatchObject({ side: "call", action: "sell", strike: 105 });
  });

  it("iron condor = 4 legs bracketing ATM", () => {
    const legs = presetLegs("iron_condor", 100, 5);
    expect(legs).toHaveLength(4);
    const strikes = legs.map((l) => l.strike).sort((a, b) => a - b);
    expect(strikes).toEqual([90, 95, 105, 110]);
    // Short the inner strikes, long the wings.
    expect(legs.find((l) => l.strike === 95)?.action).toBe("sell");
    expect(legs.find((l) => l.strike === 105)?.action).toBe("sell");
    expect(legs.find((l) => l.strike === 90)?.action).toBe("buy");
    expect(legs.find((l) => l.strike === 110)?.action).toBe("buy");
  });

  it("butterfly = +1 wing / -2 body / +1 wing", () => {
    const legs = presetLegs("butterfly", 100, 5);
    expect(legs).toHaveLength(3);
    const body = legs.find((l) => l.strike === 100);
    expect(body?.action).toBe("sell");
    expect(body?.ratio).toBe(2);
    expect(legs.filter((l) => l.action === "buy")).toHaveLength(2);
  });
});
