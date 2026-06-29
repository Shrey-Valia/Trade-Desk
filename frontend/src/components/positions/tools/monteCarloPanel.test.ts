import { describe, expect, it } from "vitest";

import { legsFromSelection } from "./MonteCarloPanel";

describe("legsFromSelection (WS5 Monte-Carlo)", () => {
  it("single leg → one long leg at the chosen side/strike/premium", () => {
    const legs = legsFromSelection({ kind: "leg", side: "put", strike: 100, price: 1.5 });
    expect(legs).toEqual([
      { side: "put", action: "buy", strike: 100, contracts: 1, entry_price: 1.5 },
    ]);
  });

  it("defaults a missing side to call", () => {
    const legs = legsFromSelection({ kind: "leg", strike: 100, price: 2 });
    expect(legs[0].side).toBe("call");
  });

  it("straddle → long call + long put, premium split evenly", () => {
    const legs = legsFromSelection({ kind: "straddle", strike: 100, price: 3 });
    expect(legs).toHaveLength(2);
    expect(legs.every((l) => l.action === "buy" && l.strike === 100)).toBe(true);
    expect(legs.map((l) => l.entry_price)).toEqual([1.5, 1.5]);
    expect(legs.map((l) => l.side).sort()).toEqual(["call", "put"]);
  });
});
