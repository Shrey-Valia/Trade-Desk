import type { Trade } from "@/types/journal";

/**
 * True when `t` belongs to the ACTIVE combine.
 *
 * Scopes by combine id when both the account and the trade carry one — two
 * combines can share a tier (a copy-trade follower pair is the normal case),
 * so filtering by tier alone folds the other combine's positions/UPL into the
 * active one (wrong balance, false FAILED, over-counted scaling cap). Falls
 * back to tier only for legacy rows that predate the per-trade combine id.
 */
export function isActiveCombineTrade(
  t: Trade,
  combineId: number | null | undefined,
  activeTier: string,
): boolean {
  if (combineId != null && t.combine_id != null) {
    return t.combine_id === combineId;
  }
  return (t.tier ?? "50K") === activeTier;
}
