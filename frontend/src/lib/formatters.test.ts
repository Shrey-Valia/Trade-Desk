import { describe, expect, it } from "vitest";

import {
  formatChangeDollar,
  formatPercent,
  formatPrice,
  formatRange,
  formatVolume,
  formatVolumeRatio,
} from "@/lib/formatters";

// Non-breaking spaces appear in Intl compact output; normalize for stable
// string assertions across Node ICU versions.
const nbsp = (s: string) => s.replace(/\u00A0/g, " ");

describe("formatPrice", () => {
  it("formats USD with two fraction digits", () => {
    expect(formatPrice(1234.5)).toBe("$1,234.50");
    expect(formatPrice(0)).toBe("$0.00");
  });
  it("renders negatives with a leading minus", () => {
    expect(formatPrice(-12.3)).toBe("-$12.30");
  });
});

describe("formatChangeDollar", () => {
  it("always shows an explicit sign except for zero", () => {
    expect(formatChangeDollar(5)).toBe("+$5.00");
    expect(formatChangeDollar(-5)).toBe("-$5.00");
    // signDisplay: exceptZero — no + on zero.
    expect(formatChangeDollar(0)).toBe("$0.00");
  });
});

describe("formatPercent", () => {
  it("divides by 100 and appends % with an explicit sign", () => {
    // Input is a whole-number percent; formatter divides by 100 internally.
    expect(formatPercent(2.5)).toBe("+2.50%");
    expect(formatPercent(-1.25)).toBe("-1.25%");
    expect(formatPercent(0)).toBe("0.00%");
  });
});

describe("formatVolume", () => {
  it("uses compact notation", () => {
    expect(nbsp(formatVolume(32_400_000))).toBe("32.4M");
    expect(nbsp(formatVolume(1_500))).toBe("1.5K");
    expect(formatVolume(999)).toBe("999");
  });
});

describe("formatVolumeRatio", () => {
  it("joins today and average with a slash", () => {
    expect(nbsp(formatVolumeRatio(32_400_000, 28_100_000))).toBe("32.4M / 28.1M");
  });
});

describe("formatRange", () => {
  it("joins low and high prices with an en-dash", () => {
    expect(formatRange(100, 110.5)).toBe("$100.00 – $110.50");
  });
});
