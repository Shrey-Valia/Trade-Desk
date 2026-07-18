import { Link } from "react-router-dom";

import { LegalDocShell, LegalList, LegalSection, Strong } from "./LegalDocShell";

/**
 * Terms of Service — the trader-facing contract for the simulated prop-firm
 * product. Version 1 (services/legal.py LEGAL_DOC_VERSIONS); accepted at
 * signup and re-gated server-side at every combine purchase.
 */
export function TermsPage() {
  return (
    <LegalDocShell title="Terms of Service" updated="July 14, 2026">
      <LegalSection id="acceptance" title="1. Agreement to these Terms">
        <p>
          These Terms of Service (the <Strong>"Terms"</Strong>) are a binding
          agreement between you and Trade Desk (<Strong>"Trade Desk"</Strong>,{" "}
          <Strong>"we"</Strong>, <Strong>"us"</Strong>) governing your use of
          the Trade Desk platform, including trading combines (evaluations),
          simulated funded accounts, and every related service. By creating an
          account, purchasing a combine, or using the platform you accept
          these Terms, our{" "}
          <Link to="/privacy" className="text-amber hover:underline">
            Privacy Policy
          </Link>
          , our{" "}
          <Link to="/refund-policy" className="text-amber hover:underline">
            Refund Policy
          </Link>
          , and our{" "}
          <Link to="/risk-disclosure" className="text-amber hover:underline">
            Risk Disclosure
          </Link>
          . If you do not agree, do not use the platform.
        </p>
        <p>
          You must be at least 18 years old and legally able to enter
          contracts in your jurisdiction. One account per person; you are
          responsible for everything that happens under your credentials.
        </p>
      </LegalSection>

      <LegalSection id="nature" title="2. Nature of the service — simulated trading">
        <p>
          Trade Desk is a <Strong>simulated-trading evaluation platform</Strong>.
          Every account on the platform — evaluation combines and "funded"
          accounts alike — trades <Strong>simulated capital</Strong> in a
          paper-execution environment driven by live market data. No account
          is a brokerage account. No real securities, options, or funds of
          yours are traded, deposited, or at risk beyond the fees you pay.
          "Funded" describes a stage of the program, not a transfer of real
          trading capital.
        </p>
        <p>
          Payouts on funded-stage accounts are <Strong>performance rewards</Strong>{" "}
          calculated from simulated profits under your chosen profit split.
          They are compensation under this agreement, not investment returns.
          Trade Desk is not a broker-dealer, investment adviser, or futures
          commission merchant, and nothing on the platform is investment
          advice.
        </p>
      </LegalSection>

      <LegalSection id="fees" title="3. Fees and billing">
        <LegalList
          items={[
            <>
              <Strong>Evaluation fee</Strong> — combines bill monthly at the
              price shown at checkout for your tier, pricing path, and profit
              split. Billing continues each month until you cancel or the
              combine is archived.
            </>,
            <>
              <Strong>Activation fee</Strong> — on the Standard pricing path, a
              one-time fee (shown at purchase) is charged when a passed
              combine's funded account is activated. The No-Activation path
              carries no activation fee.
            </>,
            <>
              <Strong>Reset fee</Strong> — restarting a failed evaluation
              costs the tier's monthly rate unless you hold a free reset
              credit (banked one per monthly renewal).
            </>,
            <>
              <Strong>Cancellation</Strong> — you may cancel any combine at
              any time; it stays usable until the end of the paid period and
              then archives. See the Refund Policy for what is refundable.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="rules" title="4. Program rules">
        <p>
          Each combine tier publishes objective rules — profit target, maximum
          loss limit (MLL), daily loss limit (DLL), position-size caps,
          minimum trading days, and the consistency requirement. The
          platform's rule engine is the <Strong>authoritative record</Strong>:
          its evaluation of your account against the published rules is final,
          subject to the dispute process in Section 8. Passing an evaluation
          does not guarantee activation if these Terms were breached during
          the evaluation.
        </p>
      </LegalSection>

      <LegalSection id="conduct" title="5. Prohibited conduct">
        <p>
          The following conduct is prohibited on any account. Engaging in it
          is grounds for the remedies in Section 6, whether it occurs during
          an evaluation or on a funded-stage account:
        </p>
        <LegalList
          items={[
            <>
              <Strong>Rule breaches</Strong> — trading through, structuring
              around, or attempting to circumvent the published account rules
              (MLL, DLL, position caps, permitted instruments, or session
              rules).
            </>,
            <>
              <Strong>News-window abuse</Strong> — strategies built around
              exploiting scheduled high-impact news releases where simulated
              fills materially outperform what a live market would bear.
            </>,
            <>
              <Strong>Simulation-fill exploitation</Strong> — exploiting
              artifacts of the simulated execution model (stale quotes,
              modeled slippage, crossed or one-sided markets, zero-latency
              fills) to book profits unavailable in live markets.
            </>,
            <>
              <Strong>Correlated or copy trading across users</Strong> —
              coordinating identical or offsetting positions across accounts
              belonging to different users, or mirroring another user's
              trades. (The platform's own copy-trading feature across your
              own combines is permitted.)
            </>,
            <>
              <Strong>Hedging across accounts</Strong> — taking opposite sides
              of the same instrument across your own or others' accounts to
              lock a guaranteed outcome on at least one.
            </>,
            <>
              <Strong>Group passing / account management</Strong> — having a
              third party trade your evaluation or funded account, passing an
              evaluation on someone's behalf, or selling/buying passed
              accounts.
            </>,
            <>
              <Strong>Account sharing</Strong> — sharing credentials, holding
              multiple identities, or operating accounts for other people.
            </>,
            <>
              <Strong>Gambling-style abuse</Strong> — all-in or
              martingale-style position sizing intended to pass by variance
              rather than by a repeatable process, as identified by the
              review desk.
            </>,
            <>
              <Strong>Latency or data-feed arbitrage</Strong> — exploiting
              delays or discrepancies between the platform's data feed and
              other sources.
            </>,
            <>
              <Strong>Automation abuse</Strong> — unattended bots, scripted
              order spam, or load designed to stress or manipulate the
              matching model. Reasonable order-entry tooling is allowed.
            </>,
            <>
              <Strong>Platform manipulation</Strong> — probing, reverse
              engineering, or interfering with the platform's systems, or
              exploiting bugs instead of reporting them to support.
            </>,
            <>
              <Strong>Fraud and misrepresentation</Strong> — false identity or
              KYC information, stolen payment instruments, or materially
              false statements in a payout request or dispute.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="payouts" title="6. Payouts, denials, and remedies">
        <p>
          Payout requests on activated funded-stage accounts are reviewed by a
          human desk before payment. We may <Strong>deny a payout request,
          claw back simulated profits, reset or close an account, or
          terminate your access</Strong> when review finds a breach of Section
          4 or 5, identity or eligibility failures (including incomplete KYC
          or tax documentation), or payment fraud. A denial states its reason
          code; denied amounts are re-credited to the account's simulated
          balance except where the underlying profits are themselves voided
          as products of prohibited conduct.
        </p>
        <p>
          Payouts require a verified identity, a completed tax profile, and a
          payout method on file. Activation of a funded account additionally
          requires the e-signed funded-trader agreement.
        </p>
      </LegalSection>

      <LegalSection id="contractor" title="7. Independent-contractor status">
        <p>
          Funded-stage traders are <Strong>independent contractors</Strong>,
          not employees, partners, or agents of Trade Desk. Nothing here
          creates an employment relationship, and you are responsible for
          your own taxes on performance rewards. Where required, we report
          payments (e.g., IRS Form 1099-NEC for U.S. persons paid $600 or
          more in a year).
        </p>
      </LegalSection>

      <LegalSection id="disputes" title="8. Disputes about platform decisions">
        <p>
          If you believe a rule evaluation, payout denial, or account action
          was made in error, open a <Strong>rule-dispute ticket</Strong> from
          the Support page within 14 days of the decision. We review the
          account's full event record and respond through the same ticket.
          The outcome of that review is our final decision on the matter.
        </p>
      </LegalSection>

      <LegalSection id="liability" title="9. Disclaimers and limitation of liability">
        <p>
          The platform is provided <Strong>"as is" and "as available"</Strong>.
          Market data may be delayed, incorrect, or unavailable; simulated
          execution differs from live execution (see the Risk Disclosure). To
          the maximum extent permitted by law, our aggregate liability for
          any claim arising out of the platform is limited to the fees you
          paid us in the twelve months preceding the claim, and we are not
          liable for indirect, incidental, or consequential damages, or for
          lost simulated profits.
        </p>
      </LegalSection>

      <LegalSection id="changes" title="10. Changes, termination, and contact">
        <p>
          We may update these Terms by publishing a new version; material
          changes require your re-acceptance before further purchases. You
          may close your account at any time from Settings. We may suspend or
          terminate accounts for breach of these Terms, with remedies as
          described in Section 6. Questions about these Terms: open a ticket
          on the{" "}
          <Link to="/support" className="text-amber hover:underline">
            Support page
          </Link>{" "}
          or write to legal@tradedesk.example.
        </p>
      </LegalSection>
    </LegalDocShell>
  );
}
