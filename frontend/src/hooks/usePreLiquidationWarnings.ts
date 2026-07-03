import { useEffect, useRef } from "react";

import { useCombineStatus } from "@/hooks/useCombineStatus";
import { toast } from "@/stores/toast";

/**
 * Pre-liquidation warning toasts + header-pill urgency state.
 *
 * Watches the live combine-engine verdict (`useCombineStatus`) and fires a
 * STICKY `toast.warning()` ONCE per threshold crossing as the account
 * approaches its risk floors:
 *
 *   - MLL proximity < 15% of the trailing cushion → "near MLL floor"
 *   - DLL used       > 80% of the daily budget     → "near daily loss limit"
 *
 * The combine status polls every ~5s, so naive firing would spam a toast on
 * every poll. We de-dupe with a per-threshold "armed" ref: the warning fires
 * only on the transition INTO the danger band, and re-arms once the metric
 * recovers back out of it (with a small hysteresis margin so a value hovering
 * right on the line doesn't flap). A breach (cushion ≤ 0 / DLL ≥ budget) is
 * left to the header BREACH/DAY-LOCK badges + the backend's auto-liquidation;
 * this hook is purely the early-warning layer.
 *
 * Returns the derived urgency flags so the header can pulse the MLL/DLL pills
 * in sync with the toast (single source of truth for the threshold math).
 */

/** MLL proximity below this fraction of the trailing cushion → warn. */
export const MLL_WARN_FRACTION = 0.15;
/** DLL usage above this fraction of the budget → warn. */
export const DLL_WARN_FRACTION = 0.8;
/** Hysteresis: re-arm only once the metric recovers this far past the line,
 *  so a value parked on the threshold doesn't flap warn→clear→warn. */
const HYSTERESIS = 0.03;

export interface PreLiquidationUrgency {
  /** Live MLL cushion as a fraction of the trailing distance (0..1). */
  mllFraction: number;
  /** Live DLL usage as a fraction of the budget (0..1+). */
  dllFraction: number;
  /** MLL cushion in the warn band (but not yet breached). */
  mllNearFloor: boolean;
  /** DLL usage in the warn band (but not yet day-locked). */
  dllNearLimit: boolean;
  /** DLL exhausted — DAY LOCK in force. Distinct from the warn band: the
   *  trader is locked out NOW, not approaching it. */
  dllDayLocked: boolean;
}

export function usePreLiquidationWarnings(): PreLiquidationUrgency {
  const combine = useCombineStatus();

  // mllProximity is already clamp(cushion / trailingDistance, 0, 1) — the
  // exact fraction we want, computed once in useCombineStatus.
  const mllFraction = combine.mllProximity;
  const dllFraction =
    combine.dllBudget > 0 ? combine.dllUsedLive / combine.dllBudget : 0;

  // Danger bands — but never "warn" once already breached/locked (the header
  // shows a harder BREACH/DAY-LOCK state then; a warning would be noise).
  const mllNearFloor =
    !combine.loading &&
    combine.status !== "failed" &&
    combine.mllCushion > 0 &&
    mllFraction < MLL_WARN_FRACTION;
  const dllNearLimit =
    !combine.loading &&
    !combine.dayLocked &&
    !combine.dllDisabled && // DLL off → no DLL warning (only the MLL binds)
    combine.dllBudget > 0 &&
    dllFraction > DLL_WARN_FRACTION &&
    dllFraction < 1;
  // At/over the budget the warn band goes quiet by design — but silence is
  // wrong exactly when the trader is day-locked. Emit a DISTINCT day-locked
  // state (own toast + flag) so the lockout is unmistakable.
  const dllDayLocked =
    !combine.loading && !combine.dllDisabled && combine.dayLocked;

  // Per-threshold edge-trigger guards. True = armed (will fire on next entry).
  const mllArmed = useRef(true);
  const dllArmed = useRef(true);
  const dayLockArmed = useRef(true);

  useEffect(() => {
    if (combine.loading) return;
    if (mllNearFloor) {
      if (mllArmed.current) {
        mllArmed.current = false;
        toast.warning(
          `Approaching MLL floor — only $${Math.round(
            combine.mllCushion,
          ).toLocaleString()} of cushion left. A breach auto-liquidates your open positions.`,
          0, // sticky
        );
      }
    } else if (mllFraction > MLL_WARN_FRACTION + HYSTERESIS) {
      // Recovered comfortably out of the band → re-arm for next time.
      mllArmed.current = true;
    }
  }, [combine.loading, mllNearFloor, mllFraction, combine.mllCushion]);

  useEffect(() => {
    if (combine.loading) return;
    if (dllNearLimit) {
      if (dllArmed.current) {
        dllArmed.current = false;
        const remaining = Math.max(0, combine.dllBudget - combine.dllUsedLive);
        toast.warning(
          `Approaching daily loss limit — $${Math.round(
            remaining,
          ).toLocaleString()} of today's budget left. Hitting it day-locks new trades until the 5pm-PT settlement.`,
          0, // sticky
        );
      }
    } else if (dllFraction < DLL_WARN_FRACTION - HYSTERESIS) {
      dllArmed.current = true;
    }
  }, [
    combine.loading,
    dllNearLimit,
    dllFraction,
    combine.dllBudget,
    combine.dllUsedLive,
  ]);

  // Day-lock transition — fires ONCE when the DLL is hit, re-arms after the
  // 5pm-PT settlement lifts the lock.
  useEffect(() => {
    if (combine.loading) return;
    if (dllDayLocked) {
      if (dayLockArmed.current) {
        dayLockArmed.current = false;
        toast.error(
          "DAY LOCK — daily loss limit hit. No new trades until the 5pm-PT settlement; the account survives.",
          0, // sticky
        );
      }
    } else {
      dayLockArmed.current = true;
    }
  }, [combine.loading, dllDayLocked]);

  return { mllFraction, dllFraction, mllNearFloor, dllNearLimit, dllDayLocked };
}
