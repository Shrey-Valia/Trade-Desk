import { useJournalScope } from "@/hooks/useJournalCalendar";
import { useActivePosition } from "@/stores/activePosition";
import { useTradeTicket } from "@/stores/tradeTicket";

/**
 * Reset all SESSION-scoped client state — the zustand stores that hold
 * per-user / per-combine selection. React Query's cache is dropped separately
 * (qc.clear()); these stores live outside it and would otherwise survive a
 * signout or a user switch, leaking one user's selection into the next:
 *
 *   - activePosition.tradeId  → a foreign trade id → 404-ing analytics fetches
 *   - tradeTicket.selection   → a stale strike/side firing on the wrong account
 *   - journalScope.combineId  → the calendar pinned to a foreign combine
 *
 * Called on signout and on a fresh signin.
 */
export function resetSessionStores(): void {
  useActivePosition.getState().clear();
  useTradeTicket.getState().clear();
  useJournalScope.getState().setCombineId(null);
}
