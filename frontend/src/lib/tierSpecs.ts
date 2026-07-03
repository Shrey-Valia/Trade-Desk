import type { TierSpec } from "@/types/account";

/**
 * Tier specs — the SINGLE frontend mirror of backend TIERS
 * (backend/services/account_tiers.py) + the profit-target ladder
 * (backend/services/combine_objectives.py). KEEP IN SYNC.
 *
 * Every surface that renders tier numbers without (or before) a live
 * fetch — the landing page, the buy screen's fallback, Settings' risk
 * tab — reads from here, so an engine change is a one-line edit instead
 * of a hunt through three hand-maintained tables.
 */
export const TIER_SPECS: readonly TierSpec[] = [
  {
    key: "50K",
    label: "50K Combine",
    starting_balance: 50_000,
    trailing_distance: 2_000,
    initial_mll: 48_000,
    dll_amount: 1_500,
  },
  {
    key: "100K",
    label: "100K Combine",
    starting_balance: 100_000,
    // Topstep convention: 50K→$2k, 100K→$3k, 150K→$4.5k trailing drawdown.
    trailing_distance: 3_000,
    initial_mll: 97_000,
    dll_amount: 3_000,
  },
  {
    key: "150K",
    label: "150K Combine",
    starting_balance: 150_000,
    trailing_distance: 4_500,
    initial_mll: 145_500,
    dll_amount: 4_500,
  },
];

/** Realized profit needed to PASS — Topstep's ladder (6% of size). */
export const PROFIT_TARGETS: Record<string, number> = {
  "50K": 3_000,
  "100K": 6_000,
  "150K": 9_000,
};

export function profitTarget(tierKey: string): number {
  return PROFIT_TARGETS[tierKey] ?? 0;
}

export function tierSpec(tierKey: string): TierSpec | undefined {
  return TIER_SPECS.find((t) => t.key === tierKey);
}
