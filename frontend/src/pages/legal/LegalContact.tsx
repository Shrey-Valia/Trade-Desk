import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import {
  fetchLegalIdentity,
  LEGAL_IDENTITY_KEY,
  type LegalIdentity,
} from "@/lib/legalApi";

/**
 * Operator-supplied legal identity for the public documents.
 *
 * These pages used to hard-code `legal@tradedesk.example` (and `privacy@`,
 * and `billing@`) — addresses that bounce. A contact that silently fails is
 * worse than no contact: a user with a GDPR request or a billing dispute
 * follows the instruction, hears nothing, and reasonably concludes they were
 * ignored. Every page already offers the in-app Support page, which always
 * reaches someone, so the email is an ADDITION to that, not a replacement.
 *
 * Hence the shape below. `IfLegalContact` renders its children — the
 * connective and all — only when an address exists, so the sentence reads
 * correctly in both states:
 *
 *   configured:   "…on the Support page or email legal@example.com."
 *   unconfigured: "…on the Support page."
 *
 * An earlier version had the component emit its own Support fallback, which
 * produced "open a ticket on the Support page or open a ticket on the
 * Support page" on every page. Caught in the browser, not by a test — worth
 * remembering that a component which renders a fallback the caller also
 * renders can't be checked in isolation.
 *
 * The same honesty rule governs `LegalEntityClause`: unconfigured, it is
 * OMITTED rather than filled with boilerplate naming a jurisdiction nobody
 * chose. An obvious gap is honest; invented legalese is not.
 */

export function useLegalIdentity() {
  return useQuery({
    queryKey: LEGAL_IDENTITY_KEY,
    queryFn: fetchLegalIdentity,
    staleTime: 5 * 60_000,
  });
}

/**
 * Renders `children` only when the operator has configured a contact email.
 * Put the whole clause inside — including the "or email" that joins it to
 * the preceding sentence.
 */
export function IfLegalContact({ children }: { children: ReactNode }) {
  const identity = useLegalIdentity();
  if (!identity.data?.contact_email) return null;
  return <>{children}</>;
}

/** The configured contact as a mailto link. Empty until one is configured;
 *  callers wrap it in IfLegalContact rather than checking themselves. */
export function LegalEmail() {
  const identity = useLegalIdentity();
  const email = identity.data?.contact_email ?? "";
  if (!email) return null;
  return (
    <a href={`mailto:${email}`} className="text-amber hover:underline">
      {email}
    </a>
  );
}

/** The operating entity's name, or the product name as a neutral fallback. */
export function LegalEntityName() {
  const identity = useLegalIdentity();
  return <>{identity.data?.entity_name || "Trade Desk"}</>;
}

/**
 * Entity + governing-law clause. Renders NOTHING until an operator has
 * supplied both an entity and a contact — see the module note above.
 */
export function LegalEntityClause({ identity }: { identity?: LegalIdentity }) {
  const query = useLegalIdentity();
  const id = identity ?? query.data;
  if (!id?.configured) return null;
  return (
    <>
      <p>
        The platform is operated by <strong>{id.entity_name}</strong>
        {id.jurisdiction ? `, organised under the laws of ${id.jurisdiction}` : ""}
        {id.contact_address ? `, at ${id.contact_address}` : ""}.
      </p>
      {id.jurisdiction && (
        <p>
          These Terms are governed by the laws of {id.jurisdiction}, without
          regard to its conflict-of-laws rules, and the courts located there
          have exclusive jurisdiction over any dispute arising from them.
        </p>
      )}
    </>
  );
}
