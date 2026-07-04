import { describe, expect, it } from "vitest";

import {
  multiLegOrderPayload,
  netPremiumPerShare,
  presetLegs,
  strikeStep,
} from "./StrategyBuilder";
import type { MultiLegSpec } from "@/types/zerodte";

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

describe("netPremiumPerShare (premium-exit direction)", () => {
  // Minimal priced grid — only strike/call_price/put_price matter here.
  const rows = [
    { strike: 95, call_price: 6.0, put_price: 0.5 },
    { strike: 100, call_price: 2.0, put_price: 1.8 },
    { strike: 105, call_price: 0.6, put_price: 4.9 },
  ];

  it("prices a debit vertical as net-positive (long semantics)", () => {
    const net = netPremiumPerShare(rows, [
      { side: "call", action: "buy", strike: 100, ratio: 1 },
      { side: "call", action: "sell", strike: 105, ratio: 1 },
    ]);
    expect(net).toBeCloseTo(1.4, 10); // 2.0 − 0.6 → debit
  });

  it("prices an iron condor as net-negative (credit/short semantics)", () => {
    const net = netPremiumPerShare(rows, [
      { side: "put", action: "buy", strike: 95, ratio: 1 },
      { side: "put", action: "sell", strike: 100, ratio: 1 },
      { side: "call", action: "sell", strike: 100, ratio: 1 },
      { side: "call", action: "buy", strike: 105, ratio: 1 },
    ]);
    expect(net).toBeCloseTo(0.5 - 1.8 - 2.0 + 0.6, 10);
    expect(net!).toBeLessThan(0);
  });

  it("scales sold body legs by ratio (butterfly)", () => {
    const net = netPremiumPerShare(rows, [
      { side: "call", action: "buy", strike: 95, ratio: 1 },
      { side: "call", action: "sell", strike: 100, ratio: 2 },
      { side: "call", action: "buy", strike: 105, ratio: 1 },
    ]);
    expect(net).toBeCloseTo(6.0 - 4.0 + 0.6, 10);
  });

  it("returns null when a leg can't be priced off the grid — don't guess direction", () => {
    expect(
      netPremiumPerShare(rows, [
        { side: "call", action: "buy", strike: 112.5, ratio: 1 },
      ]),
    ).toBeNull();
    expect(netPremiumPerShare(rows, [])).toBeNull();
  });
});

describe("multiLegOrderPayload (net-debit limit wire shape)", () => {
  const legs: MultiLegSpec[] = [
    { side: "call", action: "buy", strike: 100, ratio: 1 },
    { side: "call", action: "sell", strike: 105, ratio: 1 },
  ];
  const base = {
    symbol: "SPY",
    contracts: 2,
    strategy: "vertical",
    legs,
    tp: 2,
    sl: 0.5,
  };

  it("market opens OMIT order_type/limit_price entirely (older-backend compatible)", () => {
    const p = multiLegOrderPayload({ ...base, orderType: "market", limitPrice: 1.4 });
    expect(p).toMatchObject({
      symbol: "SPY",
      contracts: 2,
      strategy: "vertical",
      legs,
      tp_premium_mult: 2,
      sl_premium_mult: 0.5,
    });
    expect(p).not.toHaveProperty("order_type");
    expect(p).not.toHaveProperty("limit_price");
  });

  it("NET LIMIT sends order_type:'limit' + limit_price", () => {
    const p = multiLegOrderPayload({ ...base, orderType: "limit", limitPrice: 1.4 });
    expect(p).toMatchObject({ order_type: "limit", limit_price: 1.4 });
  });

  it("keeps a negative (credit) net limit as-is — sign carries direction", () => {
    const p = multiLegOrderPayload({ ...base, orderType: "limit", limitPrice: -2.7 });
    expect(p?.limit_price).toBe(-2.7);
  });

  it("returns null when a limit is requested without a usable price", () => {
    expect(
      multiLegOrderPayload({ ...base, orderType: "limit", limitPrice: null }),
    ).toBeNull();
    expect(
      multiLegOrderPayload({ ...base, orderType: "limit", limitPrice: NaN }),
    ).toBeNull();
  });
});
