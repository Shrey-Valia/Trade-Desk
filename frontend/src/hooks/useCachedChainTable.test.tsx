import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useCachedChainTable } from "@/hooks/useChainTable";

/**
 * Review wave 9, finding 7: the passive cache reader must never serve a
 * BROWSED later-expiry table to 0DTE-semantic consumers (the header's
 * "expected move to today's close" pill, RollRow's strike step) — even
 * when the browsed query is the freshest entry.
 */

const table = (over: Record<string, unknown>) => ({
  underlying: "SPY",
  spot: 500,
  expiry: "2026-07-21",
  atm_strike: 500,
  iv_used: 0.2,
  iv_source: "implied_atm",
  rows: [],
  t_years_to_close: 0.001,
  session_close_iso: "2026-07-21T16:00:00-04:00",
  expiry_is_today: true,
  indicative: true,
  notice: "",
  ...over,
});

function setup(entries: Array<{ key: unknown[]; data: unknown; at: number }>) {
  const qc = new QueryClient();
  for (const e of entries) {
    qc.setQueryData(e.key, e.data, { updatedAt: e.at });
  }
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(() => useCachedChainTable("SPY"), { wrapper });
}

describe("useCachedChainTable expiry filter", () => {
  it("skips a fresher BROWSED (non-today) table in favor of today's", () => {
    const { result } = setup([
      {
        key: ["zerodte", "chain", "table", "SPY", 5, null],
        data: table({ expiry: "2026-07-21", expiry_is_today: true, spot: 500 }),
        at: 1_000,
      },
      {
        key: ["zerodte", "chain", "table", "SPY", 5, "2026-08-21"],
        data: table({ expiry: "2026-08-21", expiry_is_today: false, spot: 501 }),
        at: 2_000, // fresher — but browsed
      },
    ]);
    expect(result.current?.expiry).toBe("2026-07-21");
  });

  it("returns null when ONLY browsed tables are cached", () => {
    const { result } = setup([
      {
        key: ["zerodte", "chain", "table", "SPY", 5, "2026-08-21"],
        data: table({ expiry: "2026-08-21", expiry_is_today: false }),
        at: 2_000,
      },
    ]);
    expect(result.current).toBeNull();
  });

  it("tolerates old payloads without the flag (treated as today)", () => {
    const legacy = table({});
    delete (legacy as Record<string, unknown>).expiry_is_today;
    const { result } = setup([
      {
        key: ["zerodte", "chain", "table", "SPY", 5],
        data: legacy,
        at: 500,
      },
    ]);
    expect(result.current?.expiry).toBe("2026-07-21");
  });
});
