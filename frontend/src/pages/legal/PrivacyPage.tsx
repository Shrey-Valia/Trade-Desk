import { Link } from "react-router-dom";

import { IfLegalContact, LegalEmail } from "./LegalContact";
import { LegalDocShell, LegalList, LegalSection, Strong } from "./LegalDocShell";

/**
 * Privacy Policy — what we collect, why, how long we keep it, and the
 * GDPR/CCPA rights surface. Version 1 (services/legal.py).
 */
export function PrivacyPage() {
  return (
    <LegalDocShell title="Privacy Policy" updated="July 14, 2026">
      <LegalSection id="scope" title="1. Who we are and what this covers">
        <p>
          This policy explains how Trade Desk (<Strong>"we"</Strong>,{" "}
          <Strong>"us"</Strong>) collects, uses, and protects personal
          information when you use the Trade Desk platform — the website, the
          trading terminal, combines, funded-stage accounts, payouts, and
          support. It applies to account holders and to visitors of our
          public pages.
        </p>
      </LegalSection>

      <LegalSection id="collected" title="2. Information we collect">
        <LegalList
          items={[
            <>
              <Strong>Account data</Strong> — email address, display name, and
              a salted hash of your password (we never store the password
              itself).
            </>,
            <>
              <Strong>Identity verification (KYC)</Strong> — when you request
              your first payout: legal name, date of birth, country of
              residence, and the type of identity document you present.
              Verification results (verified / rejected and a reason) are
              stored with your account.
            </>,
            <>
              <Strong>Tax and payout data</Strong> — tax form type (W-9 /
              W-8BEN), legal name, address, country, the last four digits of
              your taxpayer identification number, and the payout method
              details you provide. Full TINs and full account numbers are
              not retained in our application database.
            </>,
            <>
              <Strong>Trading activity</Strong> — every simulated order,
              fill, position, rule event, and account-lifecycle event. This
              is the core product record and also our evidence base for rule
              review.
            </>,
            <>
              <Strong>Billing records</Strong> — charges, refunds, and
              subscription state for your combines. (Checkout is simulated
              in the current product; no real card number is collected.)
            </>,
            <>
              <Strong>Consent and signature records</Strong> — which legal
              documents you accepted, at which version, when, from which IP
              address, and the typed name on your funded-trader agreement.
            </>,
            <>
              <Strong>Support communications</Strong> — tickets you file and
              our replies.
            </>,
            <>
              <Strong>Technical data</Strong> — IP address, session
              identifiers (cookies), and standard request logs used for
              security and rate limiting.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="use" title="3. How we use it">
        <LegalList
          items={[
            "Operating the platform: running your combines, evaluating rules, processing activations and payout requests.",
            "Integrity and fraud prevention: enforcing one-account-per-person, detecting prohibited conduct (including cross-account coordination), and adjudicating payouts.",
            "Legal compliance: KYC/sanctions screening before payouts, tax reporting (e.g., 1099-NEC aggregation), and record-keeping obligations.",
            "Communications: transactional email (password resets, account lifecycle, payout decisions, support replies). We do not sell your data or run third-party advertising.",
            "Service improvement: aggregate, de-identified usage analysis.",
          ]}
        />
        <p>
          Legal bases where GDPR applies: performance of our contract with
          you, compliance with legal obligations (KYC, tax), and our
          legitimate interests in platform integrity and security.
        </p>
      </LegalSection>

      <LegalSection id="sharing" title="4. Sharing">
        <p>
          We share personal data only with: (a) service providers acting for
          us (hosting, email delivery, identity-verification and payment
          providers when enabled), bound by confidentiality; (b) authorities
          when a law, subpoena, or sanctions obligation requires it; and (c)
          successors in a merger or acquisition, under this policy. We never
          sell personal information.
        </p>
      </LegalSection>

      <LegalSection id="retention" title="5. Retention">
        <LegalList
          items={[
            <>
              <Strong>Account and trading records</Strong> — kept while your
              account is open and for up to 7 years after closure, matching
              financial record-keeping and dispute windows.
            </>,
            <>
              <Strong>KYC and tax records</Strong> — kept for the period
              required by anti-money-laundering and tax law (typically 5–7
              years after the relationship ends).
            </>,
            <>
              <Strong>Consent and e-sign records</Strong> — kept as long as
              the underlying agreement can be disputed.
            </>,
            <>
              <Strong>Support tickets</Strong> — kept 3 years after closure.
            </>,
            <>
              <Strong>Server logs</Strong> — rotated on a short cycle
              (typically 90 days) unless preserved for an investigation.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection id="rights" title="6. Your rights (GDPR / CCPA)">
        <p>
          Depending on where you live, you may have the right to{" "}
          <Strong>access</Strong> the personal data we hold about you,{" "}
          <Strong>correct</Strong> it, <Strong>delete</Strong> it,{" "}
          <Strong>export</Strong> it in a portable format,{" "}
          <Strong>restrict or object</Strong> to certain processing, and{" "}
          <Strong>not be discriminated against</Strong> for exercising these
          rights (CCPA). Deletion is subject to the retention obligations in
          Section 5 — KYC, tax, and consent records we are legally required
          to keep are retained even after an account is deleted.
        </p>
        <p>
          To exercise any right, open a ticket on the{" "}
          <Link to="/support" className="text-amber hover:underline">
            Support page
          </Link>
          <IfLegalContact>
            {" "}
            or email <LegalEmail />
          </IfLegalContact>
          . We respond within 30 days
          (GDPR) or 45 days (CCPA). EU/UK users may also lodge a complaint
          with their supervisory authority.
        </p>
      </LegalSection>

      <LegalSection id="security" title="7. Security">
        <p>
          Passwords are stored as salted hashes; sessions are cookie-based
          with server-side revocation; password-reset tokens are single-use,
          short-lived, and stored only as digests; payout-method details are
          never written to logs. Access to production data is restricted to
          operators who need it, and admin actions are recorded in an
          append-only audit log.
        </p>
      </LegalSection>

      <LegalSection id="cookies" title="8. Cookies">
        <p>
          We use one strictly-necessary session cookie to keep you signed in.
          We do not use advertising or cross-site tracking cookies.
        </p>
      </LegalSection>

      <LegalSection id="changes" title="9. Changes and contact">
        <p>
          We may update this policy; material changes are versioned and
          re-presented for acceptance. To reach us, open a ticket on the{" "}
          <Link to="/support" className="text-amber hover:underline">
            Support page
          </Link>
          <IfLegalContact>
            {" "}
            or email <LegalEmail />
          </IfLegalContact>
          .
        </p>
      </LegalSection>
    </LegalDocShell>
  );
}
