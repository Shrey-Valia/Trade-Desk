import { Link } from "react-router-dom";

import { LegalDocShell, LegalList, LegalSection, Strong } from "./LegalDocShell";

/**
 * Risk Disclosure — options/0DTE risk, the simulated-environment
 * differences, and the no-guarantee statements. Version 1
 * (services/legal.py); accepted at signup and re-gated at purchase.
 */
export function RiskDisclosurePage() {
  return (
    <LegalDocShell title="Risk Disclosure" updated="July 14, 2026">
      <LegalSection id="read-first" title="1. Read this before you trade">
        <p>
          This disclosure describes the material risks of using Trade Desk.
          It cannot list every risk. By accepting it you confirm you
          understand that <Strong>options trading is speculative</Strong>,
          that the platform is a <Strong>simulation</Strong> whose results do
          not predict live-market results, and that{" "}
          <Strong>no outcome — funding, payouts, or income — is
          guaranteed</Strong>.
        </p>
      </LegalSection>

      <LegalSection id="options" title="2. Options risk">
        <p>
          The platform's instruments are exchange-listed equity and index
          options. Even in simulation, the strategies you practice carry the
          risk profile of real options:
        </p>
        <LegalList
          items={[
            "A long option can expire worthless — a 100% loss of the premium — and most of an option's value can evaporate in minutes on an adverse move.",
            "Short (written) options carry losses that can far exceed the credit received; uncovered short calls have theoretically unlimited risk.",
            "Leverage cuts both ways: small moves in the underlying produce outsized percentage swings in option value.",
            "Time decay (theta) erodes long-option value continuously, fastest near expiry; being right about direction but wrong about timing still loses.",
            "Implied-volatility changes (vega) can move an option against you even when the underlying goes your way.",
            "Liquidity varies by strike and expiry — wide bid/ask spreads make round-trip costs material, and some contracts barely trade at all.",
          ]}
        />
      </LegalSection>

      <LegalSection id="zerodte" title="3. Zero-DTE (0DTE) risk">
        <p>
          Trade Desk gives prominent access to <Strong>same-day-expiry
          ("0DTE") options</Strong>. These are among the most volatile listed
          instruments available to retail-style traders:
        </p>
        <LegalList
          items={[
            "Gamma is extreme near expiry — position deltas can flip in seconds, and P&L can swing violently on small underlying moves.",
            "There is no time to recover: every position resolves today, and theta decay near expiry is at its steepest.",
            "Quotes can be fast-moving, one-sided, or momentarily crossed around news and the open/close; execution assumptions matter enormously (see Section 4).",
            "Consistent profitability in 0DTE options is rare. Treat any strategy that appears to work in simulation with heightened suspicion before assuming it survives live conditions.",
          ]}
        />
      </LegalSection>

      <LegalSection id="simulation" title="4. Simulated-environment differences">
        <p>
          Every Trade Desk account trades <Strong>simulated capital against
          a modeled market</Strong>. Fills are simulated against the
          prevailing <Strong>NBBO with modeled slippage</Strong>, and{" "}
          <Strong>may differ — sometimes materially — from the executions a
          real order would have received</Strong>. Specific differences
          include:
        </p>
        <LegalList
          items={[
            "No market impact: your simulated orders do not move the market, consume liquidity, or sit in a real queue. Live orders of the same size might execute at worse prices or not at all.",
            "Modeled slippage is an estimate: real slippage varies with depth, volatility, and speed, and can be far larger in fast markets.",
            "Data feeds can lag, gap, or err; the sim's reference prices may differ from what another venue showed at the same instant.",
            "Halts, auction periods, and exchange-specific mechanics are approximated or absent.",
            "Assignment, exercise, and pin risk on short options are handled by simplified rules rather than the OCC process.",
            "A strategy that depends on precise fills (scalping spreads, fading stale quotes) may be profitable ONLY in simulation — and exploiting sim artifacts is prohibited conduct under the Terms.",
          ]}
        />
      </LegalSection>

      <LegalSection id="program" title="5. Program risk — no guarantee of funding or income">
        <LegalList
          items={[
            <>
              Evaluation fees are payment for access to the evaluation, not a
              deposit or an investment.{" "}
              <Strong>Most participants in evaluation-style programs do not
              pass</Strong>; you should assume fees paid are the cost of
              practice, not a path to certain income.
            </>,
            <>
              A "funded" account holds <Strong>simulated capital</Strong>.
              Payouts are performance rewards under the{" "}
              <Link to="/terms" className="text-amber hover:underline">
                Terms of Service
              </Link>{" "}
              — reviewed by a human desk, subject to identity/tax
              verification, and deniable for rule breaches.
            </>,
            "Rule limits (daily loss limit, trailing max loss) can end an evaluation or funded account in a single session. Accounts that breach are failed regardless of any open-position recovery that follows.",
            "Program parameters, pricing, and rules may change between billing periods (announced in advance and versioned where consent is required).",
            "Past performance — yours or anyone's, simulated or live — does not indicate future results. Published trader results are not typical.",
          ]}
        />
      </LegalSection>

      <LegalSection id="suitability" title="6. Suitability">
        <p>
          Trade only with money you can afford to lose entirely — here, that
          means fees you can afford to spend on an evaluation that may fail.
          Trade Desk provides no personalized investment advice; nothing in
          the terminal (analytics, Greeks, Monte-Carlo projections,
          probability displays) is a recommendation to enter any trade. If
          you are unsure whether options-style risk suits your circumstances,
          consult a licensed financial adviser before purchasing a combine.
        </p>
      </LegalSection>

      <LegalSection id="acknowledge" title="7. Your acknowledgement">
        <p>
          By accepting this disclosure you acknowledge that you have read and
          understood it; that simulated results do not predict live results;
          that fills are modeled and may differ from real executions; that
          funding and payouts are conditional program outcomes, not
          guarantees; and that you alone are responsible for your trading
          decisions on the platform.
        </p>
      </LegalSection>
    </LegalDocShell>
  );
}
