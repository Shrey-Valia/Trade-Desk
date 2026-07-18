import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Modal } from "@/components/ui/Modal";
import { LEGAL_STATUS_KEY, signFundedAgreement } from "@/lib/legalApi";
import { toast } from "@/stores/toast";
import type { CombineOut } from "@/types/combine";

const TITLE_ID = "funded-agreement-title";

/**
 * Typed-name e-sign of the funded-trader agreement — the gate in front of
 * funded-account activation (backend: POST /api/combines/{id}/activate-account
 * 403s "agreement_required: …" until a SIGNED acceptance exists).
 *
 * Presents the agreement's material terms as a summary, requires the
 * trader to type their name as the signature, records it via
 * POST /api/legal/sign-funded-agreement, then hands control back to the
 * caller (`onSigned`) to run the activation itself.
 */
export function FundedAgreementModal({
  combine,
  open,
  onClose,
  onSigned,
  activating,
}: {
  combine: CombineOut;
  open: boolean;
  onClose: () => void;
  /** Called after the signature is recorded — proceed with activation. */
  onSigned: () => void;
  /** The caller's activation mutation is in flight. */
  activating: boolean;
}) {
  const qc = useQueryClient();
  const [typedName, setTypedName] = useState("");

  const sign = useMutation({
    mutationFn: (name: string) => signFundedAgreement(name),
    onSuccess: (status) => {
      qc.setQueryData(LEGAL_STATUS_KEY, status);
      onSigned();
    },
    onError: (e) =>
      toast.error((e as Error)?.message || "Couldn't record your signature."),
  });

  const name = typedName.trim();
  const keepPct = Math.round((combine.profit_split ?? 0.8) * 100);
  const pending = sign.isPending || activating;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || pending) return;
    sign.mutate(name);
  };

  return (
    <Modal
      open={open}
      onClose={pending ? () => undefined : onClose}
      labelledBy={TITLE_ID}
      panelClassName="w-full max-w-lg"
    >
      <form
        onSubmit={onSubmit}
        className="border border-hairline-strong bg-tier-1 flex flex-col max-h-[85vh]"
        style={{ borderRadius: 4 }}
      >
        <div className="px-4 py-3 border-b border-hairline">
          <h2
            id={TITLE_ID}
            className="text-medium font-medium text-fg-primary m-0"
          >
            Funded-trader agreement
          </h2>
          <p className="text-tiny text-fg-tertiary-2 mt-0.5 m-0">
            {combine.name} · {combine.tier}
            {combine.activation_fee > 0
              ? ` · one-time $${combine.activation_fee} activation fee`
              : " · no activation fee"}
          </p>
        </div>

        <div className="px-4 py-3 overflow-y-auto flex flex-col gap-2.5 text-tiny text-fg-secondary leading-5">
          <p className="m-0">
            Before this funded account activates, you sign the funded-trader
            agreement. In short:
          </p>
          <Term label="Independent contractor">
            You trade as an independent contractor — not an employee, partner,
            or agent of Trade Desk — and you are responsible for your own
            taxes on performance rewards.
          </Term>
          <Term label="Simulated capital">
            The funded account holds simulated capital in a paper-execution
            environment. No real funds are traded, and payouts are
            performance rewards calculated from simulated profits — not
            investment returns.
          </Term>
          <Term label="Profit split">
            You keep {keepPct}% of eligible simulated profits, per the split
            chosen at purchase.
          </Term>
          <Term label="Payout rules">
            Payout requests require verified identity (KYC), a tax profile,
            and a payout method on file. Each request is reviewed by a human
            desk and must satisfy the program's payout conditions (minimums,
            winning-day counts, spacing, loss-limit buffers). Requests can be
            denied for cause with a stated reason.
          </Term>
          <Term label="Prohibited conduct">
            The Terms of Service conduct rules keep applying — no account
            sharing, cross-user coordinated or copy trading, simulation-fill
            or news-window exploitation, group passing, or rule
            circumvention. Breaches can void profits, deny payouts, or
            terminate the account.
          </Term>
          <p className="m-0 text-fg-tertiary-2">
            The full terms are in the{" "}
            <Link
              to="/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber hover:underline"
            >
              Terms of Service
            </Link>{" "}
            (sections 5–7). Typing your name below is your electronic
            signature on this agreement.
          </p>
        </div>

        <div className="px-4 py-3 border-t border-hairline flex flex-col gap-2.5">
          <label className="flex flex-col gap-1">
            <span
              className="uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 11, letterSpacing: "0.08em" }}
            >
              Type your full legal name to sign
            </span>
            <input
              type="text"
              value={typedName}
              onChange={(e) => setTypedName(e.target.value)}
              maxLength={120}
              autoComplete="name"
              spellCheck={false}
              placeholder="Your name"
              className="h-9 px-2.5 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary placeholder:text-fg-tertiary focus:border-amber focus:outline-none"
              style={{ fontSize: 13 }}
            />
          </label>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={pending}
              className="h-9 px-3 text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name || pending}
              className="h-9 px-4 uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 disabled:opacity-50 disabled:cursor-not-allowed rounded-btn font-medium"
              style={{ fontSize: 12 }}
            >
              {sign.isPending
                ? "Signing…"
                : activating
                  ? "Activating…"
                  : combine.activation_fee > 0
                    ? `Sign & activate — $${combine.activation_fee}`
                    : "Sign & activate"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function Term({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-hairline bg-tier-2 px-2.5 py-2" style={{ borderRadius: 4 }}>
      <div
        className="uppercase tracking-label-up text-amber mb-0.5"
        style={{ fontSize: 11 }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}
