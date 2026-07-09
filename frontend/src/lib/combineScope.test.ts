import { describe, expect, it } from "vitest";

import { sumOpenContracts } from "@/hooks/useOpenContractsCount";
import { isActiveCombineTrade } from "@/lib/combineScope";
import type { Trade } from "@/types/journal";

function mk(partial: Partial<Trade>): Trade {
  return {
    id: 1,
    symbol: "SPY",
    strategy: "long_call",
    legs: [],
    entry_date: "2026-01-01T00:00:00Z",
    entry_underlying_price: 100,
    net_debit_credit: 0,
    status: "open",
    is_paper: true,
    tier: "50K",
    origin: "execution",
    order_type: "market",
    time_in_force: "gtc",
    tags: [],
    mistake_tags: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...partial,
  } as Trade;
}

const leg = (contracts: number) => ({
  side: "call" as const,
  action: "buy" as const,
  strike: 100,
  expiry: "2030-01-01",
  contracts,
  entry_price: 1,
});

describe("isActiveCombineTrade", () => {
  it("scopes by combine_id — two same-tier combines stay distinct", () => {
    const a = mk({ combine_id: 1, tier: "50K" });
    const b = mk({ combine_id: 2, tier: "50K" });
    expect(isActiveCombineTrade(a, 1, "50K")).toBe(true);
    expect(isActiveCombineTrade(b, 1, "50K")).toBe(false); // same tier, other combine
  });

  it("falls back to tier when the trade has no combine_id (legacy row)", () => {
    const legacy = mk({ combine_id: null, tier: "100K" });
    expect(isActiveCombineTrade(legacy, 1, "100K")).toBe(true);
    expect(isActiveCombineTrade(legacy, 1, "50K")).toBe(false);
  });
});

describe("sumOpenContracts combine scoping", () => {
  it("counts only the active combine's open legs, not a same-tier sibling's", () => {
    const trades = [
      mk({ combine_id: 1, tier: "50K", legs: [leg(3)] }),
      mk({ combine_id: 2, tier: "50K", legs: [leg(5)] }), // same tier, other combine
    ];
    // Scoped by combine id → each combine sees only its own open size...
    expect(sumOpenContracts(trades, "50K", 1)).toBe(3);
    expect(sumOpenContracts(trades, "50K", 2)).toBe(5);
    // ...whereas the old tier-only filter would have wrongly summed both to 8.
  });
});
