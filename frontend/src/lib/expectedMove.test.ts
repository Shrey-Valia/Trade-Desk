import { describe, expect, it } from "vitest";

import { expectedMoveFromChain, optionMid } from "@/lib/expectedMove";
import type { ChainStrikeRow } from "@/types/zerodte";

/** Minimal valid row; overrides layer the case-specific quote shape. */
function row(overrides: Partial<ChainStrikeRow> & { strike: number }): ChainStrikeRow {
  return {
    call_price: 1.0,
    call_source: "quote",
    call_open_interest: null,
    put_price: 1.0,
    put_source: "quote",
    put_open_interest: null,
    is_atm: false,
    call_delta: 0.5,
    call_theta: -0.1,
    put_delta: -0.5,
    put_theta: -0.1,
    call_bid: null,
    call_ask: null,
    put_bid: null,
    put_ask: null,
    call_volume: null,
    put_volume: null,
    ...overrides,
  };
}

describe("optionMid", () => {
  it("returns (bid+ask)/2 when both sides are quoted", () => {
    expect(optionMid(1.0, 1.2, 5)).toBeCloseTo(1.1, 10);
  });

  it("falls back to the indicative price when either side is null", () => {
    expect(optionMid(null, 1.2, 0.95)).toBe(0.95);
    expect(optionMid(1.0, null, 0.95)).toBe(0.95);
    expect(optionMid(null, null, 0.95)).toBe(0.95);
  });

  it("falls back on a crossed/empty book instead of averaging garbage", () => {
    expect(optionMid(1.5, 1.0, 0.95)).toBe(0.95); // crossed
    expect(optionMid(0, 0, 0.95)).toBe(0.95); // empty
  });

  it("returns null when neither quote nor fallback is usable", () => {
    expect(optionMid(null, null, null)).toBeNull();
    expect(optionMid(null, null, 0)).toBeNull();
  });
});

describe("expectedMoveFromChain", () => {
  const rows = [
    row({ strike: 495, call_bid: 5.0, call_ask: 5.2, put_bid: 0.4, put_ask: 0.6 }),
    row({ strike: 500, call_bid: 1.9, call_ask: 2.1, put_bid: 1.7, put_ask: 1.9 }),
    row({ strike: 505, call_bid: 0.3, call_ask: 0.5, put_bid: 4.8, put_ask: 5.0 }),
  ];

  it("picks the strike nearest the spot and sums the call+put mids", () => {
    // spot 500.9 → nearest strike 500; EM = 2.0 + 1.8 = 3.8.
    const em = expectedMoveFromChain(rows, 500.9);
    expect(em).not.toBeNull();
    expect(em!.strike).toBe(500);
    expect(em!.em).toBeCloseTo(3.8, 10);
    expect(em!.pct).toBeCloseTo((3.8 / 500.9) * 100, 10);
  });

  it("re-anchors ATM as the spot moves", () => {
    expect(expectedMoveFromChain(rows, 503.2)!.strike).toBe(505);
  });

  it("falls back to the row's call_price/put_price when bid/ask are null", () => {
    const modelRows = [
      row({ strike: 500, call_price: 2.05, put_price: 1.85 }), // all quotes null
    ];
    const em = expectedMoveFromChain(modelRows, 500);
    expect(em!.em).toBeCloseTo(3.9, 10);
  });

  it("hides (null) when the chain or spot is unusable", () => {
    expect(expectedMoveFromChain([], 500)).toBeNull();
    expect(expectedMoveFromChain(null, 500)).toBeNull();
    expect(expectedMoveFromChain(rows, null)).toBeNull();
    expect(expectedMoveFromChain(rows, 0)).toBeNull();
    // Row with no usable prices on one side → don't print a half-straddle EM.
    const broken = [row({ strike: 500, call_price: 0, put_price: 1.85 })];
    expect(expectedMoveFromChain(broken, 500)).toBeNull();
  });
});
