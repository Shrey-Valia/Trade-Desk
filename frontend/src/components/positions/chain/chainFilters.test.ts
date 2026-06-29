import { describe, expect, it } from "vitest";

import type { ChainStrikeRow } from "@/types/zerodte";

import { applyChainFilters, DEFAULT_CHAIN_FILTERS } from "./RightChain";

function row(
  strike: number,
  opts: Partial<ChainStrikeRow> = {},
): ChainStrikeRow {
  return {
    strike,
    call_price: 1,
    call_source: "quote",
    call_open_interest: 100,
    put_price: 1,
    put_source: "quote",
    put_open_interest: 100,
    is_atm: false,
    call_delta: 0,
    call_theta: 0,
    put_delta: 0,
    put_theta: 0,
    ...opts,
  };
}

const ROWS: ChainStrikeRow[] = [
  row(90, { call_open_interest: 10, put_open_interest: 10 }),
  row(95, { call_open_interest: 50, put_open_interest: 50 }),
  row(100, { is_atm: true }),
  row(105, { call_source: "bs", put_source: "bs" }),
  row(110, { call_open_interest: 2000, put_open_interest: 5 }),
];

describe("applyChainFilters (WS5 chain filtering)", () => {
  it("default filters are a no-op", () => {
    expect(applyChainFilters(ROWS, 100, DEFAULT_CHAIN_FILTERS)).toHaveLength(5);
  });

  it("moneyness band keeps rows within ±band strikes of ATM", () => {
    const out = applyChainFilters(ROWS, 100, { ...DEFAULT_CHAIN_FILTERS, band: 1 });
    // ATM (100) + the two adjacent (95, 105).
    expect(out.map((r) => r.strike).sort((a, b) => a - b)).toEqual([95, 100, 105]);
  });

  it("min open interest drops thin strikes but keeps ATM", () => {
    const out = applyChainFilters(ROWS, 100, {
      ...DEFAULT_CHAIN_FILTERS,
      minOpenInterest: 100,
    });
    // 90 (10) and 95 (50) drop; 110 keeps (call OI 2000 ≥ 100); ATM always kept.
    const strikes = out.map((r) => r.strike).sort((a, b) => a - b);
    expect(strikes).toContain(100);
    expect(strikes).toContain(110);
    expect(strikes).not.toContain(90);
    expect(strikes).not.toContain(95);
  });

  it("live-quotes-only hides rows with BS fallback on both sides", () => {
    const out = applyChainFilters(ROWS, 100, {
      ...DEFAULT_CHAIN_FILTERS,
      liveQuotesOnly: true,
    });
    expect(out.map((r) => r.strike)).not.toContain(105);
  });

  it("ATM row always survives every filter", () => {
    const out = applyChainFilters(ROWS, 100, {
      band: 0,
      minOpenInterest: 100_000,
      liveQuotesOnly: true,
    });
    expect(out.map((r) => r.strike)).toContain(100);
  });
});
