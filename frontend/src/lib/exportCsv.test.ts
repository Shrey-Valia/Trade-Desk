import { describe, expect, it } from "vitest";

import { executionsToCsv } from "@/lib/exportCsv";
import type { Trade } from "@/types/journal";

const base = {
  entry_date: "2026-07-18T14:00:00Z",
  entry_underlying_price: 500,
  net_debit_credit: 100,
  is_paper: true,
  origin: "execution",
  order_type: "market",
  time_in_force: "gtc",
  tier: "50K",
  tags: [],
  mistake_tags: [],
  created_at: "2026-07-18T14:00:00Z",
  updated_at: "2026-07-18T14:00:00Z",
} as const;

function trade(over: Partial<Trade>): Trade {
  return {
    id: 1,
    symbol: "SPY",
    strategy: "long_straddle",
    legs: [
      { side: "call", action: "buy", strike: 500, expiry: "2026-07-18", contracts: 2, entry_price: 1.1 },
      { side: "put", action: "buy", strike: 500, expiry: "2026-07-18", contracts: 2, entry_price: 1.0 },
    ],
    status: "closed",
    exit_date: "2026-07-18T19:00:00Z",
    exit_underlying_price: 505,
    realized_pnl: 120,
    close_reason: "take_profit",
    ...base,
    ...over,
  } as Trade;
}

describe("executionsToCsv (fills report)", () => {
  it("emits one row per leg entry plus a close row per closed position", () => {
    const lines = executionsToCsv([trade({})]).split("\r\n");
    expect(lines).toHaveLength(4); // header + 2 entry legs + 1 close
    expect(lines[1]).toContain("entry");
    expect(lines[1]).toContain("1.1");
    expect(lines[2]).toContain("put");
    expect(lines[3]).toContain("close");
    expect(lines[3]).toContain("take_profit");
    expect(lines[3]).toContain("120");
  });

  it("open positions get entry rows but no close row", () => {
    const lines = executionsToCsv([
      trade({ status: "open", exit_date: null, realized_pnl: null, close_reason: null }),
    ]).split("\r\n");
    expect(lines).toHaveLength(3); // header + 2 entries
    expect(lines.join("\n")).not.toContain("close,");
  });

  it("working and cancelled orders never appear (no fill happened)", () => {
    const lines = executionsToCsv([
      trade({ status: "working" }),
      trade({ id: 2, status: "cancelled" }),
    ]).split("\r\n");
    expect(lines).toHaveLength(1); // header only
  });
});
