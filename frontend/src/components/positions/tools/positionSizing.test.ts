import { describe, expect, it } from "vitest";

import { computeSizing } from "./PositionSizer";

describe("computeSizing (WS5 position sizer)", () => {
  it("sizes contracts off risk budget / per-contract stop loss", () => {
    // balance 100k, risk 1% → $1000 budget; stop $0.50/sh → $50/contract.
    const r = computeSizing({ balance: 100_000, riskPct: 1, stopDistance: 0.5 });
    expect(r.valid).toBe(true);
    expect(r.suggested).toBe(20); // 1000 / 50
    expect(r.maxLoss).toBe(1000); // 20 × 50
    expect(r.riskBudget).toBe(1000);
  });

  it("floors to whole contracts", () => {
    // $1000 budget, $0.30/sh stop → $30/contract → 33.3 → 33.
    const r = computeSizing({ balance: 100_000, riskPct: 1, stopDistance: 0.3 });
    expect(r.suggested).toBe(33);
    expect(r.maxLoss).toBeCloseTo(33 * 30, 6);
  });

  it("invalid when budget below one contract's stop", () => {
    // $10 budget, $5/sh stop → $500/contract → 0 contracts.
    const r = computeSizing({ balance: 1000, riskPct: 1, stopDistance: 5 });
    expect(r.valid).toBe(false);
    expect(r.suggested).toBe(0);
    expect(r.reason).toMatch(/below one contract/i);
  });

  it("guards missing balance / risk / stop", () => {
    expect(computeSizing({ balance: 0, riskPct: 1, stopDistance: 1 }).valid).toBe(false);
    expect(computeSizing({ balance: 100_000, riskPct: 0, stopDistance: 1 }).valid).toBe(false);
    expect(computeSizing({ balance: 100_000, riskPct: 1, stopDistance: null }).valid).toBe(false);
    expect(computeSizing({ balance: 100_000, riskPct: 1, stopDistance: 0 }).valid).toBe(false);
  });
});
