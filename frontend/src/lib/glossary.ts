/**
 * Glossary of key prop-firm / options terms surfaced in the Help overlay
 * (WS6). Plain data so it can be searched/rendered without pulling in any
 * component. Kept terse — these are quick-reference definitions, not a
 * textbook. Term wording mirrors the labels used across the terminal
 * (MLL pill, DLL pill, the 0DTE chain, the greeks readouts).
 */
import { TOOLTIPS } from "@/lib/tooltips";

export interface GlossaryTerm {
  term: string;
  /** Expanded name, when the term is an acronym. */
  full?: string;
  definition: string;
}

export const GLOSSARY: GlossaryTerm[] = [
  {
    term: "MLL",
    full: "Maximum Loss Limit",
    definition:
      "The hard floor your account balance (including open unrealized P&L) may never touch. Breaching it FAILS the combine permanently. The floor trails up with new equity highs and re-baselines only at the 5pm-PT settlement.",
  },
  {
    term: "DLL",
    full: "Daily Loss Limit",
    definition:
      "The most you may lose in a single trading day before a DAY LOCK halts new trades. Unlike the MLL it is not fatal — it lifts at the next 5pm-PT settlement. Can be tuned or switched off per tier in Settings → Risk.",
  },
  {
    term: "Combine",
    definition:
      "The paid evaluation account you trade to prove consistency. Pass it (hit the profit target, minimum trading days, and consistency rule without breaching the MLL) to unlock payouts.",
  },
  {
    term: "0DTE",
    full: "Zero Days To Expiration",
    definition:
      "An option that expires the same trading day. Cheap and fast-moving: theta decay and gamma are extreme, so a small move in the underlying can double or zero the premium within hours.",
  },
  {
    term: "Greeks",
    definition:
      "The sensitivities of an option's price. Delta — move per $1 of underlying. Gamma — how fast delta changes. Theta — value lost per day to time decay. Vega — sensitivity to implied volatility.",
  },
  {
    term: "Breakeven (BE)",
    definition:
      "The underlying price at which the position neither makes nor loses money at expiry. For a long call it's strike + premium; for a long put, strike − premium. Shown as the magenta band on the chart.",
  },
  {
    term: "Scaling plan",
    definition:
      "The cap on how many contracts you may hold at once, which grows with your built equity. The trade ticket and the server both enforce the current cap.",
  },
  {
    term: "RP&L / UP&L",
    full: "Realized / Unrealized P&L",
    definition:
      "RP&L is profit/loss already booked by closing trades today. UP&L is the live mark-to-market on positions still open. BAL = EOD baseline + RP&L + UP&L.",
  },
  {
    term: "Trailing stop",
    definition:
      "An exit that follows the option's favorable high-water mark by a fixed distance and closes the position when the mark retraces past it. Attached optionally at open from the trade ticket.",
  },
  {
    term: "Payout",
    definition:
      "A withdrawal of profit from a passed/funded combine. Subject to the profit-split (80/20 or 50/50) chosen at purchase.",
  },
  {
    term: "BAL",
    full: "Account balance",
    definition: TOOLTIPS.bal,
  },
  {
    term: "Closed P&L",
    full: "Realized P&L (same as RP&L)",
    definition: TOOLTIPS.closed_pnl,
  },
  {
    term: "MLL cushion",
    definition: TOOLTIPS.mll_cushion,
  },
  {
    term: "BP",
    full: "Buying power",
    definition: TOOLTIPS.buying_power,
  },
  {
    term: "Consistency target",
    definition: TOOLTIPS.consistency_target,
  },
  {
    term: "Profit target",
    definition: TOOLTIPS.profit_target,
  },
  {
    term: "Trading days",
    definition: TOOLTIPS.trading_days,
  },
  {
    term: "High-water mark",
    definition:
      "The highest balance your combine has reached. The MLL floor trails up from it and never drops back down within a trading session.",
  },
  {
    term: "Funded",
    definition:
      "A combine you've passed and activated. Only funded combines can request payouts.",
  },
  {
    term: "R-multiple",
    definition:
      "A trade's result measured in multiples of the risk you took (1R = the amount risked). +2R means you made twice what you risked; −1R means you lost your full risk.",
  },
  {
    term: "ATM",
    full: "At-the-money",
    definition:
      "The option strike closest to the current underlying price. ATM options are the most liquid and the most sensitive to a move in the stock.",
  },
  {
    term: "EM",
    full: "Expected move",
    definition: TOOLTIPS.expected_move,
  },
  {
    term: "Max pain",
    definition: TOOLTIPS.max_pain,
  },
  {
    term: "Gamma flip",
    definition: TOOLTIPS.gamma_flip,
  },
  {
    term: "Call wall",
    definition: TOOLTIPS.call_wall,
  },
  {
    term: "Put wall",
    definition: TOOLTIPS.put_wall,
  },
  {
    term: "IV Rank",
    full: "Implied-volatility rank",
    definition: TOOLTIPS.iv_rank,
  },
  {
    term: "VRP",
    full: "Volatility risk premium",
    definition: TOOLTIPS.vrp,
  },
  {
    term: "Skew",
    full: "25-delta skew",
    definition: TOOLTIPS.skew_25d,
  },
  {
    term: "P/C ratio",
    full: "Put/call ratio",
    definition: TOOLTIPS.pc_ratio,
  },
];
