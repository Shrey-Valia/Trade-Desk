import { useEffect, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { relativeTime } from "@/components/positions/panelChrome";
import { LoadError } from "@/components/ui/LoadError";
import {
  ADMIN_INVITES_PAGE_SIZE,
  adminKeys,
  createAdminInvite,
  errorMessage,
  fetchAdminInvites,
  revokeAdminInvite,
  type AdminInvite,
  type InviteStatus,
} from "@/lib/adminApi";
import { toast } from "@/stores/toast";

import {
  ActionModal,
  Btn,
  Chip,
  Field,
  FilterChips,
  fmtDateTime,
  INPUT_CLS,
  inviteStatusTone,
  NUM_CLS,
  Pager,
  Panel,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TH_CLS,
} from "./adminUi";

/**
 * Invites — the closed-launch signup gate. Mint a code, hand it to one
 * person, watch it get redeemed; revoke it if it goes to the wrong place.
 *
 * The banner up top is the point of the screen: minting codes does nothing
 * unless SIGNUP_REQUIRE_INVITE is actually on, and an operator who mints
 * ten codes against an open signup page would otherwise have no way to
 * discover that.
 */

type Filter = "all" | InviteStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "redeemed", label: "Redeemed" },
  { key: "revoked", label: "Revoked" },
  { key: "expired", label: "Expired" },
];

export function AdminInvites() {
  const [filter, setFilter] = useState<Filter>("active");
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [minting, setMinting] = useState(false);
  const [revoking, setRevoking] = useState<AdminInvite | null>(null);

  // Debounced search — typing shouldn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(input.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [input]);

  const status = filter === "all" ? undefined : filter;
  const invites = useQuery({
    queryKey: adminKeys.invites(status, q, page),
    queryFn: () => fetchAdminInvites(status, q, page),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

  const gateOff = invites.data && !invites.data.require_invite;

  return (
    <div className="flex flex-col gap-3">
      {gateOff && (
        <div
          role="status"
          className="border border-warning px-3 py-2 text-tiny text-warning"
          style={{ borderRadius: 2 }}
        >
          Signup is <strong>open</strong> — anyone with the URL can create an
          account, and these codes aren't required. Set{" "}
          <code className={NUM_CLS}>SIGNUP_REQUIRE_INVITE=1</code> and restart
          the app to close it.
        </div>
      )}
      <Panel
        label={
          <>
            Invites{" "}
            {invites.data && (
              <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
                · {invites.data.total}
              </span>
            )}
          </>
        }
        actions={
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <input
              type="search"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Search code, email or note…"
              className={`${INPUT_CLS} w-56 max-w-full`}
              style={{ fontSize: 12 }}
            />
            <FilterChips
              options={FILTERS}
              value={filter}
              onChange={(f) => {
                setFilter(f);
                setPage(1);
              }}
            />
            <Btn kind="primary" onClick={() => setMinting(true)}>
              New invite
            </Btn>
          </div>
        }
      >
        {invites.isPending ? (
          <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
            Loading invites…
          </div>
        ) : invites.isError ? (
          <LoadError subject="the invite list" onRetry={invites.refetch} />
        ) : invites.data.invites.length === 0 ? (
          <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
            {q
              ? `No invites match “${q}”.`
              : filter === "active"
                ? "No live invites — mint one to let someone in."
                : "Nothing here."}
          </div>
        ) : (
          <>
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>Code</th>
                  <th className={TH_CLS}>Status</th>
                  <th className={TH_CLS}>For</th>
                  <th className={TH_CLS}>Note</th>
                  <th className={TH_CLS}>Created</th>
                  <th className={TH_CLS}>Expires</th>
                  <th className={TH_CLS} />
                </tr>
              </thead>
              <tbody>
                {invites.data.invites.map((inv) => (
                  <InviteRow
                    key={inv.id}
                    invite={inv}
                    onRevoke={() => setRevoking(inv)}
                  />
                ))}
              </tbody>
            </table>
            <Pager
              page={invites.data.page}
              total={invites.data.total}
              pageSize={ADMIN_INVITES_PAGE_SIZE}
              onPage={setPage}
            />
          </>
        )}
      </Panel>
      {minting && (
        <MintModal
          defaultTtlDays={invites.data?.default_ttl_days ?? 14}
          onClose={() => setMinting(false)}
        />
      )}
      {revoking && (
        <RevokeModal invite={revoking} onClose={() => setRevoking(null)} />
      )}
    </div>
  );
}

// -- one row -------------------------------------------------------------------

function InviteRow({
  invite,
  onRevoke,
}: {
  invite: AdminInvite;
  onRevoke: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(invite.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is permission-gated and absent over plain HTTP — the code
      // is right there in the cell to select by hand, so this is a
      // non-event rather than an error worth a toast.
    }
  };

  return (
    <tr className="hover:bg-tier-2">
      <td className={`${TD_CLS} ${NUM_CLS}`}>
        <button
          type="button"
          onClick={copy}
          title="Copy code"
          className="text-fg-primary hover:text-amber"
        >
          {invite.code}
          <span className="text-fg-tertiary-2 ml-1.5" style={{ fontSize: 11 }}>
            {copied ? "copied" : "copy"}
          </span>
        </button>
      </td>
      <td className={TD_CLS}>
        <Chip tone={inviteStatusTone(invite.status)}>{invite.status}</Chip>
      </td>
      <td className={TD_CLS}>
        {invite.redeemed_by_email ? (
          <span className="text-fg-primary">{invite.redeemed_by_email}</span>
        ) : invite.email ? (
          <span className="text-fg-secondary">{invite.email}</span>
        ) : (
          <span className="text-fg-tertiary-2">anyone</span>
        )}
      </td>
      <td className={`${TD_CLS} text-fg-tertiary-2`}>{invite.note ?? "—"}</td>
      <td
        className={`${TD_CLS} ${NUM_CLS} text-fg-tertiary-2`}
        title={fmtDateTime(invite.created_at)}
      >
        {relativeTime(invite.created_at)}
      </td>
      <td className={`${TD_CLS} ${NUM_CLS} text-fg-tertiary-2`}>
        {invite.expires_at ? fmtDateTime(invite.expires_at) : "never"}
      </td>
      <td className={`${TD_CLS} text-right`}>
        {invite.status === "active" || invite.status === "expired" ? (
          <Btn kind="danger" onClick={onRevoke}>
            Revoke
          </Btn>
        ) : null}
      </td>
    </tr>
  );
}

// -- mint ----------------------------------------------------------------------

function MintModal({
  defaultTtlDays,
  onClose,
}: {
  defaultTtlDays: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [ttl, setTtl] = useState(String(defaultTtlDays));
  const [minted, setMinted] = useState<AdminInvite | null>(null);

  const mint = useMutation({
    mutationFn: () =>
      createAdminInvite({
        email: email.trim() || undefined,
        note: note.trim() || undefined,
        expires_in_days: Number(ttl) >= 0 ? Number(ttl) : undefined,
      }),
    onSuccess: (inv) => {
      // Stay open and show the code — with mail still console-only, the
      // operator has to read it off this screen to send it by hand.
      setMinted(inv);
      toast.success("Invite created.");
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: adminKeys.invitesPrefix });
      qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    },
  });

  const ttlNum = Number(ttl);
  const ttlValid = ttl.trim() !== "" && Number.isFinite(ttlNum) && ttlNum >= 0;

  if (minted) {
    const link = `${window.location.origin}/signup?invite=${encodeURIComponent(minted.code)}`;
    return (
      <ActionModal
        open
        title="Invite created"
        confirmLabel="Done"
        onConfirm={onClose}
        onClose={onClose}
      >
        <div className="flex flex-col gap-2">
          <div className="text-tiny text-fg-tertiary-2">
            Send this to {minted.email ?? "whoever you're inviting"}. It stays
            listed, so you can copy it again later.
          </div>
          <div
            className={`${NUM_CLS} text-medium text-amber border border-hairline-strong px-3 py-2 text-center`}
            style={{ borderRadius: 2 }}
          >
            {minted.code}
          </div>
          <Field label="Or send the one-click link">
            <input
              readOnly
              value={link}
              onFocus={(e) => e.currentTarget.select()}
              className={INPUT_CLS}
              style={{ fontSize: 12 }}
            />
          </Field>
        </div>
      </ActionModal>
    );
  }

  return (
    <ActionModal
      open
      title="New invite"
      confirmLabel="Create invite"
      pending={mint.isPending}
      disabled={!ttlValid}
      onConfirm={() => mint.mutate()}
      onClose={onClose}
    >
      <div className="flex flex-col gap-3">
        <Field label="Bind to email (optional)">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="trader@example.com"
            className={INPUT_CLS}
            style={{ fontSize: 12 }}
          />
          <span className="text-tiny text-fg-tertiary-2">
            Only that address can redeem it. Leave blank for a code anyone
            holding it can use.
          </span>
        </Field>
        <Field label="Note (who is this for?)">
          <input
            type="text"
            value={note}
            maxLength={200}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Beta cohort 1 — met at the meetup"
            className={INPUT_CLS}
            style={{ fontSize: 12 }}
          />
        </Field>
        <Field label="Expires in (days — 0 for never)">
          <input
            type="number"
            min={0}
            max={365}
            value={ttl}
            onChange={(e) => setTtl(e.target.value)}
            className={INPUT_CLS}
            style={{ fontSize: 12 }}
          />
        </Field>
      </div>
    </ActionModal>
  );
}

// -- revoke --------------------------------------------------------------------

function RevokeModal({
  invite,
  onClose,
}: {
  invite: AdminInvite;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");

  const revoke = useMutation({
    mutationFn: () => revokeAdminInvite(invite.id, reason.trim() || undefined),
    onSuccess: () => {
      toast.success(`${invite.code} revoked.`);
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: adminKeys.invitesPrefix });
      qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    },
  });

  return (
    <ActionModal
      open
      title={`Revoke ${invite.code}?`}
      confirmLabel="Revoke invite"
      confirmKind="danger"
      pending={revoke.isPending}
      onConfirm={() => revoke.mutate()}
      onClose={onClose}
    >
      <div className="flex flex-col gap-3">
        <div className="text-tiny text-fg-tertiary-2">
          The code stops working immediately. This can't be undone — mint a
          new one if you change your mind.
        </div>
        <Field label="Reason (optional — lands in the audit log)">
          <input
            type="text"
            value={reason}
            maxLength={300}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Sent to the wrong address"
            className={INPUT_CLS}
            style={{ fontSize: 12 }}
          />
        </Field>
      </div>
    </ActionModal>
  );
}
