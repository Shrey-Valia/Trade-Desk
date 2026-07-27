import { describe, expect, it } from "vitest";

import { STALE_QUOTE_SECONDS, quoteStaleness } from "./RightChain";

const T0 = Date.parse("2026-07-25T18:00:00Z");
const iso = (offsetSec: number) => new Date(T0 + offsetSec * 1000).toISOString();

describe("quoteStaleness", () => {
  it("is not stale when the quote is fresh during market hours", () => {
    const { stale, ageSec } = quoteStaleness(iso(0), T0 + 5_000, true);
    expect(stale).toBe(false);
    expect(ageSec).toBe(5);
  });

  it("flags stale once the quote passes the threshold during market hours", () => {
    const { stale, ageSec } = quoteStaleness(
      iso(0),
      T0 + (STALE_QUOTE_SECONDS + 1) * 1000,
      true,
    );
    expect(stale).toBe(true);
    expect(ageSec).toBe(STALE_QUOTE_SECONDS + 1);
  });

  it("never flags stale while the market is closed (quotes legitimately old)", () => {
    const { stale } = quoteStaleness(iso(0), T0 + 3_600_000, false);
    expect(stale).toBe(false);
  });

  it("does not flag exactly at the threshold (strict >)", () => {
    const { stale } = quoteStaleness(iso(0), T0 + STALE_QUOTE_SECONDS * 1000, true);
    expect(stale).toBe(false);
  });

  it("handles a missing or unparseable timestamp without flagging", () => {
    expect(quoteStaleness(null, T0, true)).toEqual({ stale: false, ageSec: null });
    expect(quoteStaleness("not-a-date", T0, true)).toEqual({
      stale: false,
      ageSec: null,
    });
  });

  it("clamps a future timestamp to age 0 (clock skew)", () => {
    const { stale, ageSec } = quoteStaleness(iso(10), T0, true);
    expect(ageSec).toBe(0);
    expect(stale).toBe(false);
  });
});
