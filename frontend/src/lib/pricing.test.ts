import { describe, expect, it } from "vitest";

import {
  ACTIVATION_FEE,
  BASE_MONTHLY,
  MAX_CONTRACTS,
  NO_ACTIVATION_PREMIUM,
  SPLIT_DISCOUNT,
  activationFee,
  monthlyPrice,
  splitLabel,
  splitPct,
  splitTokenFromValue,
} from "@/lib/pricing";

// This matrix mirrors backend/services/pricing.py and is the money math
// the landing + buy screens render fetch-free. The tests pin the exact
// dollar amounts so an accidental constant drift fails loudly.

describe("monthlyPrice", () => {
  it("returns the activation / 80-20 base for each tier", () => {
    expect(monthlyPrice("50K")).toBe(69);
    expect(monthlyPrice("100K")).toBe(119);
    expect(monthlyPrice("150K")).toBe(169);
  });

  it("adds the no-activation premium", () => {
    expect(monthlyPrice("50K", "no_activation")).toBe(69 + NO_ACTIVATION_PREMIUM);
    expect(monthlyPrice("150K", "no_activation")).toBe(169 + 50);
  });

  it("subtracts the 50/50 split discount", () => {
    expect(monthlyPrice("100K", "activation", "50_50")).toBe(119 - SPLIT_DISCOUNT);
  });

  it("stacks the no-activation premium and the split discount", () => {
    // 119 base + 50 premium − 10 split = 159.
    expect(monthlyPrice("100K", "no_activation", "50_50")).toBe(159);
  });

  it("returns 0 for an unknown tier (graceful default)", () => {
    expect(monthlyPrice("999K")).toBe(0);
    // Premium/discount still apply on top of the 0 base.
    expect(monthlyPrice("999K", "no_activation", "50_50")).toBe(40);
  });

  it("keeps BASE_MONTHLY in lockstep with the computed defaults", () => {
    for (const tier of Object.keys(BASE_MONTHLY)) {
      expect(monthlyPrice(tier)).toBe(BASE_MONTHLY[tier]);
    }
  });
});

describe("activationFee", () => {
  it("charges $149 on the activation path", () => {
    expect(activationFee("activation")).toBe(ACTIVATION_FEE);
    expect(activationFee("activation")).toBe(149);
  });
  it("charges $0 on the no-activation path", () => {
    expect(activationFee("no_activation")).toBe(0);
  });
});

describe("split helpers", () => {
  it("labels split tokens", () => {
    expect(splitLabel("80_20")).toBe("80 / 20");
    expect(splitLabel("50_50")).toBe("50 / 50");
  });

  it("returns the trader's whole-percent share", () => {
    expect(splitPct("80_20")).toBe(80);
    expect(splitPct("50_50")).toBe(50);
  });

  it("snaps a stored float back to its token", () => {
    expect(splitTokenFromValue(0.8)).toBe("80_20");
    expect(splitTokenFromValue(0.5)).toBe("50_50");
    // Rounds to nearest whole percent before snapping.
    expect(splitTokenFromValue(0.499)).toBe("50_50");
    expect(splitTokenFromValue(0.81)).toBe("80_20");
  });
});

describe("MAX_CONTRACTS scaling ladder", () => {
  it("mirrors the backend scaling plan (50K→5, 100K→10, 150K→15)", () => {
    expect(MAX_CONTRACTS["50K"]).toBe(5);
    expect(MAX_CONTRACTS["100K"]).toBe(10);
    expect(MAX_CONTRACTS["150K"]).toBe(15);
  });
});
