/**
 * Combine pricing — mirrors backend/services/pricing.py. KEEP IN SYNC.
 *
 * Trade Desk is a paper / simulated prop firm (no real money moves), but the
 * pricing shown is real. The backend computes the authoritative amount at
 * purchase from the same matrix; these constants drive instant, fetch-free
 * rendering on the public landing page and the buy screen.
 *
 * Two PATHS (chosen at purchase): "activation" (lower monthly + a one-time
 * $149 fee when the account funds) or "no_activation" (+$50/mo, $0 fee).
 * Two SPLITS: "80_20" (standard, normal price) or "50_50" (−$10/mo).
 */

export type PricingPath = "activation" | "no_activation";
export type SplitToken = "80_20" | "50_50";

/** With-activation, 80/20 base monthly (D1 + $20 options premium). */
export const BASE_MONTHLY: Record<string, number> = {
  "50K": 69,
  "100K": 119,
  "150K": 169,
};

export const ACTIVATION_FEE = 149;
export const NO_ACTIVATION_PREMIUM = 50;
export const SPLIT_DISCOUNT = 10;

export const SPLIT_VALUES: Record<SplitToken, number> = {
  "80_20": 0.8,
  "50_50": 0.5,
};

/** Max position (contracts) cap per tier — the top of the scaling ladder.
 *  Mirrors backend/services/scaling_plan.py (50K→5, 100K→10, 150K→15). */
export const MAX_CONTRACTS: Record<string, number> = {
  "50K": 5,
  "100K": 10,
  "150K": 15,
};

/** Monthly subscription for a (tier, path, split). */
export function monthlyPrice(
  tier: string,
  path: PricingPath = "activation",
  split: SplitToken = "80_20",
): number {
  let price = BASE_MONTHLY[tier] ?? 0;
  if (path === "no_activation") price += NO_ACTIVATION_PREMIUM;
  if (split === "50_50") price -= SPLIT_DISCOUNT;
  return price;
}

/** One-time activation fee for the path ($149 on activation, else $0). */
export function activationFee(path: PricingPath): number {
  return path === "activation" ? ACTIVATION_FEE : 0;
}

/** "80 / 20" | "50 / 50" — display label for a split token. */
export function splitLabel(token: SplitToken): string {
  return token === "50_50" ? "50 / 50" : "80 / 20";
}

/** Trader's profit share as a whole percent (80 | 50). */
export function splitPct(token: SplitToken): number {
  return token === "50_50" ? 50 : 80;
}

/** Snap a stored split float (0.8 / 0.5) back to its token. */
export function splitTokenFromValue(value: number): SplitToken {
  return Math.round(value * 100) === 50 ? "50_50" : "80_20";
}
