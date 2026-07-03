import type { ChainStrikeRow } from "@/types/zerodte";

/**
 * Expected move (ToS "MMM"-style) — pure helpers, unit-tested.
 *
 * The ATM straddle's price is what the options market charges for a move
 * in EITHER direction by expiry; for a 0DTE chain that's the implied move
 * to today's close. It shrinks through the day as theta burns.
 */

/**
 * Mid of an NBBO pair, falling back to the row's indicative price when the
 * quote is missing (null bid/ask) or crossed/empty. Returns null when
 * neither source is usable.
 */
export function optionMid(
  bid: number | null | undefined,
  ask: number | null | undefined,
  fallback: number | null | undefined,
): number | null {
  if (
    bid != null &&
    ask != null &&
    Number.isFinite(bid) &&
    Number.isFinite(ask) &&
    ask > 0 &&
    ask >= bid &&
    bid >= 0
  ) {
    return (bid + ask) / 2;
  }
  if (fallback != null && Number.isFinite(fallback) && fallback > 0) {
    return fallback;
  }
  return null;
}

export interface ExpectedMove {
  /** The strike used as ATM (nearest to spot). */
  strike: number;
  /** $ expected move to the close = ATM call mid + ATM put mid (per share). */
  em: number;
  /** em / spot × 100. */
  pct: number;
}

/**
 * EM from the chain table the terminal already fetches: find the strike
 * nearest the live spot, sum the call+put mids (bid/ask mid, falling back
 * to the row's model/indicative price). Null whenever the derivation
 * isn't trustworthy — caller hides the pill entirely.
 */
export function expectedMoveFromChain(
  rows: readonly ChainStrikeRow[] | null | undefined,
  spot: number | null | undefined,
): ExpectedMove | null {
  if (!rows?.length || spot == null || !Number.isFinite(spot) || spot <= 0) {
    return null;
  }
  let atm: ChainStrikeRow | null = null;
  for (const r of rows) {
    if (!Number.isFinite(r.strike)) continue;
    if (!atm || Math.abs(r.strike - spot) < Math.abs(atm.strike - spot)) {
      atm = r;
    }
  }
  if (!atm) return null;
  const callMid = optionMid(atm.call_bid, atm.call_ask, atm.call_price);
  const putMid = optionMid(atm.put_bid, atm.put_ask, atm.put_price);
  if (callMid == null || putMid == null) return null;
  const em = callMid + putMid;
  if (!Number.isFinite(em) || em <= 0) return null;
  return { strike: atm.strike, em, pct: (em / spot) * 100 };
}
