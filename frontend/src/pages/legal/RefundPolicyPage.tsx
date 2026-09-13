import { Link } from "react-router-dom";

import { IfLegalContact, LegalEmail } from "./LegalContact";
import { LegalDocShell, LegalList, LegalSection, Strong } from "./LegalDocShell";

/**
 * Refund Policy — the 14-day / no-trades rule, what is never refundable,
 * and the chargeback consequence. Version 1 (services/legal.py).
 */
export function RefundPolicyPage() {
  return (
    <LegalDocShell title="Refund Policy" updated="July 14, 2026">
      <LegalSection id="summary" title="1. The short version">
        <LegalList
          items={[
            <>
              A combine purchase is refundable within{" "}
              <Strong>14 days</Strong> — but <Strong>only if no trades have
              been placed</Strong> on that combine.
            </>,
            <>
              <Strong>Reset fees and activation fees are non-refundable</Strong>,
              always.
            </>,
            <>
              Filing a <Strong>chargeback</Strong> instead of contacting us
              results in account termination.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="evaluation" title="2. Evaluation (combine) fees">
        <p>
          The monthly combine fee buys access to the evaluation environment.
          You may request a full refund of a combine's initial purchase
          within <Strong>14 calendar days</Strong> of the charge{" "}
          <Strong>provided no trades — filled, working, or cancelled — have
          been placed</Strong> on that combine. The first order you submit
          consumes the evaluation and ends refund eligibility for that
          purchase, whatever the order's outcome.
        </p>
        <p>
          Monthly <Strong>renewal charges</Strong> keep an in-progress
          evaluation or funded-stage account running and are not refundable
          once the new billing period has started. To avoid a renewal, cancel
          the combine before its period end from the Accounts page — it stays
          usable through the paid period and then archives without further
          charges.
        </p>
      </LegalSection>

      <LegalSection id="nonrefundable" title="3. Never refundable">
        <LegalList
          items={[
            <>
              <Strong>Reset fees</Strong> — a reset restarts a failed
              evaluation immediately; the service is delivered in full the
              moment the account is reset.
            </>,
            <>
              <Strong>Activation fees</Strong> — the one-time funded-account
              activation charge (Standard path) is earned when the funded
              account is activated and payouts unlock.
            </>,
            <>
              <Strong>Partially used billing periods</Strong> — cancelling
              mid-period stops future charges but does not prorate the
              current one.
            </>,
            <>
              <Strong>Accounts terminated for cause</Strong> — fees on
              accounts closed for breach of the{" "}
              <Link to="/terms" className="text-amber hover:underline">
                Terms of Service
              </Link>{" "}
              (prohibited conduct, fraud, account sharing) are forfeited.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="how" title="4. How to request a refund">
        <p>
          Open a <Strong>billing ticket</Strong> from the{" "}
          <Link to="/support" className="text-amber hover:underline">
            Support page
          </Link>
          <IfLegalContact>
            {" "}
            (or email <LegalEmail /> from your account email)
          </IfLegalContact>{" "}
          with the combine's account code. We verify the no-trades condition
          against the account's order record — the platform's event log is
          authoritative — and answer within 5 business days. Approved refunds
          are returned to the original payment method; processing time
          depends on your payment provider, typically 5–10 business days.
        </p>
      </LegalSection>

      <LegalSection id="chargebacks" title="5. Chargebacks">
        <p>
          If you dispute a charge with your bank or card issuer{" "}
          <Strong>without first giving us the chance to resolve it</Strong>,
          we treat the dispute as a breach of the Terms of Service:{" "}
          <Strong>your account and all combines are terminated</Strong>,
          pending payout requests are cancelled, and we may contest the
          chargeback with our records (order history, consent records, IP
          logs). You remain welcome to raise any billing problem through
          support first — legitimate errors on our side are refunded without
          argument.
        </p>
      </LegalSection>

      <LegalSection id="payouts" title="6. Payouts are not refunds">
        <p>
          Performance rewards on funded-stage accounts are governed by the{" "}
          <Link to="/terms" className="text-amber hover:underline">
            Terms of Service
          </Link>{" "}
          (Section 6), not by this policy. A denied payout is not a
          refundable event; denied amounts are handled as described there.
        </p>
      </LegalSection>

      <LegalSection id="law" title="7. Statutory rights">
        <p>
          Nothing in this policy limits non-waivable rights you hold under
          the consumer-protection law of your place of residence. Where such
          law grants a longer or unconditional withdrawal right, that law
          prevails to the extent of the conflict.
        </p>
      </LegalSection>
    </LegalDocShell>
  );
}
