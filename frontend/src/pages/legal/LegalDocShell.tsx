import { Link } from "react-router-dom";

/**
 * Shared frame for the public legal pages (terms / privacy / refund / risk).
 * Rendered outside the authed rail shell — reachable from the landing footer,
 * signup, and checkout without a session — so it carries its own full-page
 * chrome on the design-system tokens (tier surfaces, fg ramp, Archivo
 * display headings).
 *
 * Reading measure: the text column is capped at 42rem (~70ch at 13px) so
 * long paragraphs stay scannable.
 */
export function LegalDocShell({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-tier-0 text-fg-primary">
      <div className="mx-auto px-6 py-12" style={{ maxWidth: "42rem" }}>
        <nav className="flex items-center justify-between gap-4 flex-wrap">
          <Link
            to="/"
            className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
          >
            ← Trade Desk
          </Link>
          <span className="flex items-center gap-3 text-tiny uppercase tracking-label-up text-fg-tertiary-2">
            <Link to="/terms" className="hover:text-amber">
              Terms
            </Link>
            <Link to="/privacy" className="hover:text-amber">
              Privacy
            </Link>
            <Link to="/refund-policy" className="hover:text-amber">
              Refunds
            </Link>
            <Link to="/risk-disclosure" className="hover:text-amber">
              Risk
            </Link>
          </span>
        </nav>
        <h1
          className="mt-8 font-display font-semibold text-fg-primary"
          style={{ fontSize: 30, letterSpacing: "-0.02em", lineHeight: 1.15 }}
        >
          {title}
        </h1>
        <p className="mt-2 text-tiny uppercase tracking-label-up text-fg-tertiary-2">
          Last updated {updated} · Version 1
        </p>
        <div className="mt-8 flex flex-col gap-8 text-sm leading-6 text-fg-secondary">
          {children}
        </div>
        <div className="mt-12 border-t border-hairline pt-4 text-tiny text-fg-tertiary">
          Trade Desk is a simulated-trading evaluation platform. Nothing on
          this page or this site is investment, legal, or tax advice.
        </div>
      </div>
    </div>
  );
}

/** One titled, deep-linkable section (`/terms#payouts` etc.). */
export function LegalSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-6">
      <h2
        className="font-display font-semibold text-fg-primary border-b border-hairline pb-2"
        style={{ fontSize: 17, letterSpacing: "-0.01em" }}
      >
        {title}
      </h2>
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  );
}

/** Bulleted list with the app's hairline discipline (no default markers). */
export function LegalList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5">
          <span aria-hidden className="text-amber shrink-0 select-none">
            —
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Inline emphasis for defined terms / hard numbers inside body copy. */
export function Strong({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-fg-primary">{children}</strong>;
}
