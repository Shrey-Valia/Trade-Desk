import { describe, expect, it } from "vitest";

import { PROFIT_TARGETS, TIER_SPECS, profitTarget, tierSpec } from "@/lib/tierSpecs";

/**
 * Pin test — the frontend tier mirror vs the numbers the backend engine
 * enforces (backend/services/account_tiers.py + combine_objectives.py).
 * A prop firm's risk numbers are quasi-contractual: the landing page once
 * advertised a $4,000 100K trail against a $3,000 engine because three
 * hand-maintained copies drifted. If this test fails, the ENGINE is the
 * source of truth — update tierSpecs.ts, never the other way around.
 */
describe("tierSpecs mirrors the backend engine", () => {
  it("pins the Topstep-convention trailing distances", () => {
    expect(tierSpec("50K")?.trailing_distance).toBe(2_000);
    expect(tierSpec("100K")?.trailing_distance).toBe(3_000);
    expect(tierSpec("150K")?.trailing_distance).toBe(4_500);
  });

  it("pins starting balances and derived initial MLLs", () => {
    for (const t of TIER_SPECS) {
      expect(t.initial_mll).toBe(t.starting_balance - t.trailing_distance);
    }
    expect(tierSpec("50K")?.starting_balance).toBe(50_000);
    expect(tierSpec("100K")?.starting_balance).toBe(100_000);
    expect(tierSpec("150K")?.starting_balance).toBe(150_000);
  });

  it("pins the DLL amounts (3% of size)", () => {
    expect(tierSpec("50K")?.dll_amount).toBe(1_500);
    expect(tierSpec("100K")?.dll_amount).toBe(3_000);
    expect(tierSpec("150K")?.dll_amount).toBe(4_500);
  });

  it("pins the profit-target ladder (6% of size)", () => {
    expect(profitTarget("50K")).toBe(3_000);
    expect(profitTarget("100K")).toBe(6_000);
    expect(profitTarget("150K")).toBe(9_000);
    expect(Object.keys(PROFIT_TARGETS)).toHaveLength(TIER_SPECS.length);
  });
});
