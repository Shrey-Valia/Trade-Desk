/**
 * Centralized tooltip definitions for jargon used across the dashboard.
 *
 * Each entry is two sentences:
 *   1. WHAT the term means — precise, technical, definition-grade.
 *   2. WHY traders care — what the number lets you decide.
 *
 * Style rules:
 *   • Define the term before naming consequences.
 *   • One concrete example or actionable framing in the second sentence.
 *   • No "obviously" / "clearly" / "simply" — those condescend.
 *   • No implementation notes ("on free tier", "currently iterating",
 *     "see warning") — UI handles those separately. Definitions are evergreen.
 *   • Plain ASCII characters. Native title= renders best that way.
 *
 * Edits here propagate everywhere via the TOOLTIPS export.
 */

export const TOOLTIPS = {
  // ---------------------------------------------------------------------
  // Account / prop-firm metrics (management pages + terminal header)
  // ---------------------------------------------------------------------
  bal:
    "Your combine's account balance right now: the day's starting baseline plus realized P&L plus any open unrealized P&L. " +
    "This is the number the loss limits are measured against.",

  closed_pnl:
    "Profit or loss already locked in by trades you've closed on this combine (the same figure the terminal labels RP&L, realized P&L). " +
    "It excludes open positions — those show separately as unrealized P&L.",

  mll:
    "Maximum Loss Limit: the hard floor your balance may never touch — breaching it fails the combine permanently. " +
    "It trails up as you set new equity highs and re-baselines at the 5pm-PT settlement.",

  dll:
    "Daily Loss Limit: the most you can lose in one trading day before new trades are locked for the rest of the session. " +
    "Unlike the MLL it isn't fatal — it resets at the next 5pm-PT settlement.",

  mll_cushion:
    "How much your balance can still fall before it hits the MLL floor and the combine fails. " +
    "The smaller this gets, the less room you have — treat it as your true risk budget.",

  buying_power:
    "The capital available to open new positions on this combine right now. " +
    "It shrinks as you tie up money in open trades and as losses reduce your balance.",

  consistency_target:
    "A pass rule: no single trading day may account for more than 50% of your total realized profit. " +
    "It stops one lucky day from carrying the whole evaluation — spread gains across sessions.",

  profit_target:
    "The realized-profit amount you must reach to pass the combine and get funded. " +
    "Hit it while meeting the minimum trading days and consistency rule, without breaching the MLL.",

  trading_days:
    "The count of distinct days you've actually traded versus the minimum required to pass. " +
    "A pass needs the profit target AND at least this many separate trading days.",

  // ---------------------------------------------------------------------
  // Options metrics row
  // ---------------------------------------------------------------------
  iv_rank:
    "Where current 30-day implied volatility sits in its 52-week range, scored 0-100. " +
    "High IV Rank means options are expensive relative to the past year — premium-selling territory.",

  vrp:
    "Volatility Risk Premium: implied vol minus realized vol, in vol points. " +
    "Positive VRP means the market is pricing more movement than the stock has actually delivered — the structural edge for premium sellers.",

  skew_25d:
    "Difference in implied vol between 25-delta puts and 25-delta calls. " +
    "Positive skew means puts cost more than equidistant calls — the market is paying up for downside protection.",

  pc_ratio:
    "Today's put volume divided by call volume across the chain. " +
    "Above 1.0 is more puts than calls (often bearish positioning); below 1.0 is more calls (bullish flow or short covering).",

  max_pain:
    "The strike where total option-holder intrinsic value is minimized at expiration. " +
    "Near expiry, spot tends to gravitate here as dealers hedge their books — treat it as a soft magnet, not a forecast.",

  // ---------------------------------------------------------------------
  // Annotated chart levels
  // ---------------------------------------------------------------------
  expected_move:
    "One standard deviation move implied by the at-the-money straddle price. " +
    "Roughly a 68% probability the underlying stays inside these bands by expiration.",

  call_wall:
    "Strike with the largest call open interest in the chain. " +
    "Often acts as resistance because dealers short calls there and sell stock as price approaches, dampening upside.",

  put_wall:
    "Strike with the largest put open interest in the chain. " +
    "Often acts as support because dealers long puts there and buy stock as price approaches, dampening downside.",

  gamma_flip:
    "Price level where dealer gamma exposure switches sign. " +
    "Above this level dealers stabilize price (sell rallies, buy dips); below it they amplify moves in the same direction.",

  // ---------------------------------------------------------------------
  // PriceHeader labels
  // ---------------------------------------------------------------------
  day_range:
    "High and low prices during today's regular trading session (9:30 AM to 4:00 PM ET). " +
    "Width of the range gauges intraday agitation.",

  fiftytwo_week_range:
    "Highest and lowest prices over the past 252 trading days (approximately one year). " +
    "Tells you where the current price sits in the recent regime — near 52w high, near 52w low, or mid-range.",

  volume:
    "Total shares traded during today's regular session so far. " +
    "Compare to the 20-day average to gauge whether today's activity is unusual.",

  avg_volume:
    "Average daily trading volume over the past 20 trading days. " +
    "The denominator behind 'today's volume is 2x average' kinds of statements — also a rough liquidity proxy.",

  er_badge:
    "Days until next scheduled earnings announcement. " +
    "Earnings introduce binary risk — IV typically expands in the days before and collapses on the print.",

  // ---------------------------------------------------------------------
  // Model signal cards
  // ---------------------------------------------------------------------
  lstm_vol:
    "LSTM neural network predicting realized volatility over the next 7 trading days, annualized. " +
    "Compare to current IV30 to spot mispriced premium — if predicted RV is lower, IV is rich.",

  catboost_er:
    "Gradient-boosted model predicting the absolute percent move on the next earnings day. " +
    "Compare to the implied move from the ATM straddle to identify cheap or rich earnings premium.",

  rf_regime:
    "Rule-based classifier of current market regime: Risk-on, Defensive, Vol Spike, Crisis, or Mean-reverting Chop. " +
    "Provides context for how to interpret the other signals — same VRP means different things in risk-on vs vol spike.",

  vol_edge:
    "Synthesized verdict combining LSTM, regime, and earnings proximity into one actionable read. " +
    "Uses transparent rules — you can see exactly which signals drove each verdict in the rationale below.",

  // ---------------------------------------------------------------------
  // Black-Scholes Greeks
  // ---------------------------------------------------------------------
  delta:
    "Sensitivity of option price to a $1 move in the underlying. " +
    "Long calls are positive delta (gain on up moves); long puts are negative (gain on down moves). Sums across multi-leg strategies.",

  gamma:
    "Rate of change of delta per $1 move in the underlying. " +
    "High gamma means the position's directional exposure shifts quickly — gamma is what makes near-ATM options whippy near expiry.",

  theta:
    "Daily time decay — how much the option price loses each day, all else equal. " +
    "Negative for long options (you pay theta); positive for short (you collect theta).",

  vega:
    "Sensitivity to a 1-point change in implied volatility. " +
    "Long options have positive vega and benefit from IV rising; short options have negative vega and benefit from IV falling.",
} as const;

export type TooltipKey = keyof typeof TOOLTIPS;
