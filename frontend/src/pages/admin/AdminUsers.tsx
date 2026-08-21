import { useEffect, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { LoadError } from "@/components/ui/LoadError";
import {
  ADMIN_USERS_PAGE_SIZE,
  adminKeys,
  adjustCombine,
  decideKyc,
  demoteUser,
  errorMessage,
  mintPasswordReset,
  fetchAdminUserDetail,
  fetchAdminUsers,
  grantResetCredit,
  promoteUser,
  refundPayment,
  suspendUser,
  unsuspendUser,
  type AdminCombine,
  type AdminPasswordReset,
  type AdminPayment,
  type AdminUserDetail,
  type CombineAdjustAction,
} from "@/lib/adminApi";
import { toast } from "@/stores/toast";

import {
  ActionModal,
  Btn,
  Chip,
  Field,
  fmtDate,
  fmtDateTime,
  fmtMoney,
  INPUT_CLS,
  kycStatusTone,
  NUM_CLS,
  Pager,
  Panel,
  payoutStateTone,
  SELECT_CLS,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TEXTAREA_CLS,
  TH_CLS,
  ticketStatusTone,
} from "./adminUi";

/**
 * Users — search → paginated table → detail drawer with the full account
 * dossier (combines, payments + refund, events, tickets, payout requests,
 * KYC decide) and the account-level actions (suspend / role / reset
 * credits). Destructive actions (suspend, refund, demote) confirm through
 * a reason-collecting modal; every mutation invalidates + refetches.
 */
export function AdminUsers() {
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Debounced search — typing shouldn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(input.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [input]);

  const users = useQuery({
    queryKey: adminKeys.users(q, page),
    queryFn: () => fetchAdminUsers(q, page),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

  return (
    <div className="flex flex-col gap-3">
      <Panel
        label={
          <>
            Users{" "}
            {users.data && (
              <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
                · {users.data.total}
              </span>
            )}
          </>
        }
        actions={
          <input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search email or name…"
            className={`${INPUT_CLS} w-64 max-w-full`}
            style={{ fontSize: 12 }}
          />
        }
      >
        {users.isPending ? (
          <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
            Loading users…
          </div>
        ) : users.isError ? (
          <LoadError subject="users" onRetry={users.refetch} />
        ) : users.data.items.length === 0 ? (
          <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
            No users match{q ? ` “${q}”` : ""}.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className={TABLE_CLS} style={TABLE_FONT}>
                <thead>
                  <tr>
                    <th className={TH_CLS}>#</th>
                    <th className={TH_CLS}>Email</th>
                    <th className={TH_CLS}>Role</th>
                    <th className={TH_CLS}>KYC</th>
                    <th className={TH_CLS}>Combines</th>
                    <th className={`${TH_CLS} text-right`}>Reset credits</th>
                    <th className={TH_CLS}>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {users.data.items.map((u) => (
                    <tr
                      key={u.id}
                      onClick={() => setSelectedId(u.id)}
                      onKeyDown={(e) => {
                        // Keyboard-operable: Enter/Space opens the user drawer
                        // (matches role="button").
                        if (e.key !== "Enter" && e.key !== " ") return;
                        e.preventDefault();
                        setSelectedId(u.id);
                      }}
                      tabIndex={0}
                      role="button"
                      aria-haspopup="dialog"
                      className="cursor-pointer hover:bg-tier-2"
                    >
                      <td className={`${TD_CLS} ${NUM_CLS}`}>{u.id}</td>
                      <td className={`${TD_CLS} text-fg-primary`}>
                        {u.email}
                        {u.display_name && (
                          <span className="text-fg-tertiary-2"> · {u.display_name}</span>
                        )}
                      </td>
                      <td className={TD_CLS}>
                        <span className="inline-flex gap-1">
                          <Chip tone={u.role === "admin" ? "amber" : "muted"}>
                            {u.role}
                          </Chip>
                          {u.suspended_at && <Chip tone="bearish">suspended</Chip>}
                        </span>
                      </td>
                      <td className={TD_CLS}>
                        <Chip tone={kycStatusTone(u.kyc_status)}>{u.kyc_status}</Chip>
                      </td>
                      <td className={TD_CLS}>
                        {Object.keys(u.combines).length === 0 ? (
                          <span className="text-fg-tertiary-2">—</span>
                        ) : (
                          Object.keys(u.combines)
                            .sort()
                            .map((s) => `${s} ${u.combines[s]}`)
                            .join(" · ")
                        )}
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {u.reset_credits}
                      </td>
                      <td className={TD_CLS}>{fmtDate(u.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              page={users.data.page}
              total={users.data.total}
              pageSize={ADMIN_USERS_PAGE_SIZE}
              onPage={setPage}
            />
          </>
        )}
      </Panel>

      {selectedId !== null && (
        <UserDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}

// -- detail drawer --------------------------------------------------------------

/** Which confirm/field modal is open inside the drawer. */
type DrawerModal =
  | { kind: "suspend" }
  | { kind: "demote" }
  | { kind: "promote" }
  | { kind: "grant" }
  | { kind: "pwreset" }
  | { kind: "kyc_reject" }
  | { kind: "refund"; payment: AdminPayment }
  | { kind: "adjust"; combine: AdminCombine }
  | null;

function UserDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: adminKeys.user(id),
    queryFn: () => fetchAdminUserDetail(id),
    staleTime: 10_000,
  });
  const [modal, setModal] = useState<DrawerModal>(null);

  // Escape closes the drawer (the inner ActionModal's own Escape handler
  // stops propagation, so a modal closes first — correct nesting).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: adminKeys.user(id) });
    qc.invalidateQueries({ queryKey: adminKeys.usersPrefix });
    qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    qc.invalidateQueries({ queryKey: adminKeys.metrics });
  };

  const act = useMutation({
    mutationFn: (vars: { run: () => Promise<unknown>; success: string }) =>
      vars.run(),
    onSuccess: (_d, vars) => {
      toast.success(vars.success);
      setModal(null);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: invalidate,
  });

  return (
    <div className="fixed inset-0 z-40">
      {/* backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onMouseDown={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-label={`User ${id} detail`}
        className="absolute inset-y-0 right-0 w-[640px] max-w-full bg-tier-1 border-l border-hairline-strong flex flex-col"
      >
        <div className="px-3.5 py-2.5 border-b border-hairline flex items-center gap-2 shrink-0">
          <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
            User <span className={NUM_CLS}>#{id}</span>
          </span>
          {detail.data && (
            <span className="text-tiny text-fg-primary truncate">
              {detail.data.email}
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close user detail"
            className="ml-auto h-7 w-7 flex items-center justify-center border border-tier-3 rounded-btn text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3">
          {detail.isPending ? (
            <div className="px-1 py-4 text-tiny text-fg-tertiary-2">
              Loading dossier…
            </div>
          ) : detail.isError ? (
            <LoadError subject="this user" onRetry={detail.refetch} />
          ) : (
            <DrawerBody
              user={detail.data}
              pending={act.isPending}
              openModal={setModal}
              onDirect={(run, success) => act.mutate({ run, success })}
            />
          )}
        </div>
      </aside>

      {detail.data && (
        <DrawerModals
          user={detail.data}
          modal={modal}
          pending={act.isPending}
          onClose={() => setModal(null)}
          onRun={(run, success) => act.mutate({ run, success })}
        />
      )}
    </div>
  );
}

function DrawerBody({
  user,
  pending,
  openModal,
  onDirect,
}: {
  user: AdminUserDetail;
  pending: boolean;
  openModal: (m: DrawerModal) => void;
  onDirect: (run: () => Promise<unknown>, success: string) => void;
}) {
  return (
    <>
      {/* identity + account actions */}
      <Panel label="Account">
        <div className="px-3 py-2.5 flex flex-col gap-2.5" style={{ fontSize: 12 }}>
          <div className="flex items-center gap-1.5 flex-wrap">
            <Chip tone={user.role === "admin" ? "amber" : "muted"}>{user.role}</Chip>
            {user.suspended_at ? (
              <Chip tone="bearish" title={fmtDateTime(user.suspended_at)}>
                suspended
              </Chip>
            ) : (
              <Chip tone="bullish">in good standing</Chip>
            )}
            <span className="text-fg-tertiary-2">
              joined {fmtDate(user.created_at)}
            </span>
            <span className="text-fg-tertiary-2">
              · reset credits <span className={`${NUM_CLS} text-fg-primary`}>{user.reset_credits}</span>
            </span>
            {user.display_name && (
              <span className="text-fg-tertiary-2">· “{user.display_name}”</span>
            )}
          </div>
          <div className="flex gap-2 flex-wrap">
            {user.suspended_at ? (
              <Btn
                kind="success"
                disabled={pending}
                onClick={() =>
                  onDirect(
                    () => unsuspendUser(user.id),
                    `${user.email} unsuspended.`,
                  )
                }
              >
                Unsuspend
              </Btn>
            ) : (
              <Btn kind="danger" disabled={pending} onClick={() => openModal({ kind: "suspend" })}>
                Suspend…
              </Btn>
            )}
            {user.role === "admin" ? (
              <Btn kind="danger" disabled={pending} onClick={() => openModal({ kind: "demote" })}>
                Demote…
              </Btn>
            ) : (
              <Btn kind="ghost" disabled={pending} onClick={() => openModal({ kind: "promote" })}>
                Promote to admin…
              </Btn>
            )}
            <Btn kind="ghost" disabled={pending} onClick={() => openModal({ kind: "grant" })}>
              Grant reset credit…
            </Btn>
            <Btn kind="ghost" disabled={pending} onClick={() => openModal({ kind: "pwreset" })}>
              Password reset link…
            </Btn>
          </div>
        </div>
      </Panel>

      {/* KYC */}
      <Panel label="KYC">
        {user.kyc === null ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">
            Never submitted.
          </div>
        ) : (
          <div className="px-3 py-2.5 flex flex-col gap-2" style={{ fontSize: 12 }}>
            <div className="flex items-center gap-2 flex-wrap">
              <Chip tone={kycStatusTone(user.kyc.status)}>{user.kyc.status}</Chip>
              <span className="text-fg-primary">{user.kyc.legal_name ?? "—"}</span>
              <span className="text-fg-tertiary-2 uppercase">{user.kyc.country ?? "—"}</span>
              <span className="text-fg-tertiary-2">
                via {user.kyc.provider} · submitted {fmtDateTime(user.kyc.submitted_at)}
                {user.kyc.decided_at && ` · decided ${fmtDateTime(user.kyc.decided_at)}`}
              </span>
            </div>
            {user.kyc.reject_reason && (
              <div className="text-tiny text-bearish">
                Rejected: {user.kyc.reject_reason}
              </div>
            )}
            {user.kyc.status === "pending" && (
              <div className="flex gap-2">
                <Btn
                  kind="success"
                  disabled={pending}
                  onClick={() =>
                    onDirect(
                      () => decideKyc(user.id, true),
                      `KYC approved for ${user.email}.`,
                    )
                  }
                >
                  Approve KYC
                </Btn>
                <Btn kind="danger" disabled={pending} onClick={() => openModal({ kind: "kyc_reject" })}>
                  Reject…
                </Btn>
              </div>
            )}
          </div>
        )}
      </Panel>

      {/* combines */}
      <Panel label={<>Combines <span className={`${NUM_CLS} normal-case text-fg-tertiary-2`}>· {user.combines.length}</span></>}>
        {user.combines.length === 0 ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">None.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>Tier</th>
                  <th className={TH_CLS}>Code</th>
                  <th className={TH_CLS}>Status</th>
                  <th className={TH_CLS}>Outcome</th>
                  <th className={`${TH_CLS} text-right`}>HWM</th>
                  <th className={TH_CLS}>Paid through</th>
                  <th className={TH_CLS} />
                </tr>
              </thead>
              <tbody>
                {user.combines.map((c) => (
                  <tr key={c.id} className="hover:bg-tier-2">
                    <td className={`${TD_CLS} ${NUM_CLS}`}>
                      {c.id}
                      {user.active_combine_id === c.id && (
                        <span className="text-amber" title="Active combine"> ●</span>
                      )}
                    </td>
                    <td className={`${TD_CLS} uppercase`}>{c.tier}</td>
                    <td className={`${TD_CLS} ${NUM_CLS} text-fg-tertiary-2`}>
                      {c.account_code}
                    </td>
                    <td className={TD_CLS}>
                      <Chip tone={c.status === "active" ? "bullish" : "muted"}>
                        {c.status}
                      </Chip>
                    </td>
                    <td className={TD_CLS}>
                      <Chip
                        tone={
                          c.outcome === "failed"
                            ? "bearish"
                            : c.outcome === "passed"
                              ? "bullish"
                              : "neutral"
                        }
                      >
                        {c.outcome}
                      </Chip>
                    </td>
                    <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                      {fmtMoney(c.hwm)}
                    </td>
                    <td className={TD_CLS}>
                      {fmtDate(c.paid_through)}
                      {c.cancel_at_period_end && (
                        <span className="text-warning" title="Cancels at period end"> ⏻</span>
                      )}
                    </td>
                    <td className={TD_CLS}>
                      <Btn
                        kind="ghost"
                        disabled={pending}
                        onClick={() => openModal({ kind: "adjust", combine: c })}
                      >
                        Adjust…
                      </Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* payments */}
      <Panel label={<>Recent payments <span className={`${NUM_CLS} normal-case text-fg-tertiary-2`}>· {user.payments.length}</span></>}>
        {user.payments.length === 0 ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">None.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>Tier</th>
                  <th className={`${TH_CLS} text-right`}>Amount</th>
                  <th className={TH_CLS}>Status</th>
                  <th className={TH_CLS}>When</th>
                  <th className={TH_CLS} />
                </tr>
              </thead>
              <tbody>
                {user.payments.map((p) => {
                  const refundable =
                    p.status !== "refunded" && p.status !== "migration_grant";
                  return (
                    <tr key={p.id} className="hover:bg-tier-2">
                      <td className={`${TD_CLS} ${NUM_CLS}`}>{p.id}</td>
                      <td className={`${TD_CLS} uppercase`}>{p.tier}</td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {fmtMoney(p.amount)}
                      </td>
                      <td className={TD_CLS}>
                        <Chip tone={p.status === "refunded" ? "bearish" : "neutral"}>
                          {p.status}
                        </Chip>
                      </td>
                      <td className={TD_CLS}>{fmtDateTime(p.created_at)}</td>
                      <td className={TD_CLS}>
                        {refundable && (
                          <Btn
                            kind="danger"
                            disabled={pending}
                            onClick={() => openModal({ kind: "refund", payment: p })}
                          >
                            Refund…
                          </Btn>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* payout requests */}
      <Panel label={<>Payout requests <span className={`${NUM_CLS} normal-case text-fg-tertiary-2`}>· {user.payout_requests.length}</span></>}>
        {user.payout_requests.length === 0 ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">None.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>Combine</th>
                  <th className={`${TH_CLS} text-right`}>Amount</th>
                  <th className={TH_CLS}>State</th>
                  <th className={TH_CLS}>Requested</th>
                  <th className={TH_CLS}>Decided</th>
                </tr>
              </thead>
              <tbody>
                {user.payout_requests.map((r) => (
                  <tr key={r.id} className="hover:bg-tier-2">
                    <td className={`${TD_CLS} ${NUM_CLS}`}>{r.id}</td>
                    <td className={`${TD_CLS} ${NUM_CLS}`}>#{r.combine_id}</td>
                    <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                      {fmtMoney(r.amount)}
                    </td>
                    <td className={TD_CLS}>
                      <Chip tone={payoutStateTone(r.state)}>
                        {r.state.replace("_", " ")}
                      </Chip>
                    </td>
                    <td className={TD_CLS}>{fmtDateTime(r.requested_at)}</td>
                    <td className={TD_CLS}>{fmtDateTime(r.decided_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* tickets */}
      <Panel label={<>Tickets <span className={`${NUM_CLS} normal-case text-fg-tertiary-2`}>· {user.tickets.length}</span></>}>
        {user.tickets.length === 0 ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">None.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>Category</th>
                  <th className={TH_CLS}>Subject</th>
                  <th className={TH_CLS}>Status</th>
                  <th className={TH_CLS}>When</th>
                </tr>
              </thead>
              <tbody>
                {user.tickets.map((t) => (
                  <tr key={t.id} className="hover:bg-tier-2">
                    <td className={`${TD_CLS} ${NUM_CLS}`}>{t.id}</td>
                    <td className={TD_CLS}>{t.category.replace("_", " ")}</td>
                    <td className={`${TD_CLS} text-fg-primary`}>{t.subject}</td>
                    <td className={TD_CLS}>
                      <Chip tone={ticketStatusTone(t.status)}>{t.status}</Chip>
                    </td>
                    <td className={TD_CLS}>{fmtDate(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* payout methods */}
      {user.payout_methods.length > 0 && (
        <Panel label="Payout methods">
          <div className="px-3 py-2.5 flex gap-1.5 flex-wrap">
            {user.payout_methods.map((mth) => (
              <Chip key={mth.id} tone={mth.is_default ? "amber" : "neutral"}>
                {mth.type} · {mth.label}
                {mth.is_default && " · default"}
              </Chip>
            ))}
          </div>
        </Panel>
      )}

      {/* recent events */}
      <Panel label={<>Recent events <span className={`${NUM_CLS} normal-case text-fg-tertiary-2`}>· {user.events.length}</span></>}>
        {user.events.length === 0 ? (
          <div className="px-3 py-3 text-tiny text-fg-tertiary-2">None.</div>
        ) : (
          <ul className="flex flex-col">
            {user.events.map((e) => (
              <li
                key={e.id}
                className="px-3 py-1.5 border-b border-hairline last:border-b-0 flex items-baseline gap-2"
                style={{ fontSize: 12 }}
              >
                <span
                  className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
                  style={{ fontSize: 11 }}
                >
                  {e.type}
                </span>
                <span className="text-fg-secondary min-w-0">{e.message}</span>
                <span className={`${NUM_CLS} text-fg-tertiary-2 ml-auto shrink-0`}>
                  {e.amount != null && `${fmtMoney(e.amount)} · `}
                  {fmtDateTime(e.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

// -- drawer modals ----------------------------------------------------------------

function DrawerModals({
  user,
  modal,
  pending,
  onClose,
  onRun,
}: {
  user: AdminUserDetail;
  modal: DrawerModal;
  pending: boolean;
  onClose: () => void;
  onRun: (run: () => Promise<unknown>, success: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [count, setCount] = useState(1);
  const [adjustAction, setAdjustAction] = useState<CombineAdjustAction>("fail");
  const [days, setDays] = useState(30);
  // The minted link is returned ONCE (only its sha256 is stored server-side),
  // so it has to be held here and shown until the operator dismisses it —
  // the shared onRun path discards mutation results.
  const [minted, setMinted] = useState<AdminPasswordReset | null>(null);
  const [copied, setCopied] = useState(false);
  const mint = useMutation({
    mutationFn: () => mintPasswordReset(user.id, reason.trim() || undefined),
    onSuccess: (data) => setMinted(data),
    onError: (e) => toast.error(errorMessage(e)),
  });

  const dismissMinted = () => {
    setMinted(null);
    setCopied(false);
    setReason("");
    onClose();
  };

  // Reset the shared field state whenever a different modal opens.
  const kindKey = modal
    ? `${modal.kind}-${modal.kind === "refund" ? modal.payment.id : modal.kind === "adjust" ? modal.combine.id : 0}`
    : "none";
  const [lastKey, setLastKey] = useState(kindKey);
  if (kindKey !== lastKey) {
    setLastKey(kindKey);
    setReason("");
    setCount(1);
    setAdjustAction("fail");
    setDays(30);
  }

  // Shown regardless of `modal`, because the link must survive the confirm
  // modal closing — losing it means minting another and invalidating this one.
  if (minted) {
    return (
      <ActionModal
        open
        onClose={dismissMinted}
        title={`Reset link for ${minted.email}`}
        confirmLabel="Done"
        onConfirm={dismissMinted}
      >
        <div className="flex flex-col gap-2">
          <div className="text-tiny text-fg-tertiary-2">
            Shown once — it isn't stored and can't be retrieved again. Send it
            to the user over a channel you trust; they set their own password.
            A copy was also queued to {minted.email}.
          </div>
          <input
            readOnly
            value={minted.reset_url}
            onFocus={(e) => e.currentTarget.select()}
            className={INPUT_CLS}
            style={{ fontSize: 12 }}
          />
          <div className="flex items-center gap-2">
            <Btn
              kind="ghost"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(minted.reset_url);
                  setCopied(true);
                } catch {
                  // Clipboard is permission-gated and absent over plain HTTP;
                  // the field above is selectable, so this is a non-event.
                }
              }}
            >
              {copied ? "Copied" : "Copy link"}
            </Btn>
            <span className="text-tiny text-fg-tertiary-2">
              Expires {fmtDateTime(minted.expires_at)}
            </span>
          </div>
        </div>
      </ActionModal>
    );
  }

  if (modal === null) return null;

  const reasonField = (label = "Reason (required, audited)") => (
    <Field label={label}>
      <textarea
        value={reason}
        maxLength={300}
        onChange={(e) => setReason(e.target.value)}
        rows={3}
        className={TEXTAREA_CLS}
        style={{ fontSize: 12, minHeight: 56 }}
      />
    </Field>
  );
  const hasReason = reason.trim().length > 0;

  switch (modal.kind) {
    case "suspend":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Suspend ${user.email}`}
          description="Suspension blocks trading immediately (the order gate checks it first). Sessions stay signed in; the account is read-only until unsuspended."
          confirmLabel="Suspend"
          confirmKind="danger"
          disabled={!hasReason}
          pending={pending}
          onConfirm={() =>
            onRun(() => suspendUser(user.id, reason.trim()), `${user.email} suspended.`)
          }
        >
          {reasonField()}
        </ActionModal>
      );
    case "demote":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Demote ${user.email}`}
          description="Removes the admin role. Refused if this would leave zero admins."
          confirmLabel="Demote to trader"
          confirmKind="danger"
          pending={pending}
          onConfirm={() =>
            onRun(
              () => demoteUser(user.id, reason.trim() || undefined),
              `${user.email} demoted to trader.`,
            )
          }
        >
          {reasonField("Reason (optional, audited)")}
        </ActionModal>
      );
    case "promote":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Promote ${user.email}`}
          description="Grants the admin role — full access to this console, every user, and the platform kill switch."
          confirmLabel="Promote to admin"
          pending={pending}
          onConfirm={() =>
            onRun(
              () => promoteUser(user.id, reason.trim() || undefined),
              `${user.email} promoted to admin.`,
            )
          }
        >
          {reasonField("Reason (optional, audited)")}
        </ActionModal>
      );
    case "grant":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Grant reset credits to ${user.email}`}
          description={`Currently holds ${user.reset_credits}. Grants clamp to the same cap monthly billing respects.`}
          confirmLabel="Grant"
          disabled={!hasReason || count < 1}
          pending={pending}
          onConfirm={() =>
            onRun(
              () => grantResetCredit(user.id, count, reason.trim()),
              `Granted ${count} reset credit${count === 1 ? "" : "s"}.`,
            )
          }
        >
          <Field label="Credits to grant">
            <input
              type="number"
              min={1}
              max={10}
              value={count}
              onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))}
              className={`${INPUT_CLS} w-24 tabular-nums`}
              style={{ fontSize: 12 }}
            />
          </Field>
          {reasonField()}
        </ActionModal>
      );
    case "pwreset":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Mint a password-reset link for ${user.email}`}
          description={
            "Does NOT set a password — you get a single-use link and the user " +
            "chooses their own. Any previous unused link stops working, and " +
            "completing this one signs the account out everywhere. Their " +
            "current session keeps working until they finish; to block access " +
            "now, suspend instead."
          }
          confirmLabel="Mint link"
          // The field is labelled "required, audited" — enforce it, and match
          // every other operator action on someone else's account (suspend,
          // demote, grant all gate on a reason). Handing out a credential is
          // exactly the thing you want a why for six months from now.
          disabled={!hasReason}
          pending={mint.isPending}
          onConfirm={() => mint.mutate()}
        >
          {reasonField()}
        </ActionModal>
      );
    case "kyc_reject":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Reject KYC for ${user.email}`}
          description="The trader sees the reason and stays blocked from payouts until re-verified."
          confirmLabel="Reject KYC"
          confirmKind="danger"
          disabled={!hasReason}
          pending={pending}
          onConfirm={() =>
            onRun(
              () => decideKyc(user.id, false, reason.trim()),
              `KYC rejected for ${user.email}.`,
            )
          }
        >
          {reasonField()}
        </ActionModal>
      );
    case "refund":
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Refund payment #${modal.payment.id}`}
          description={`${fmtMoney(modal.payment.amount)} (${modal.payment.tier.toUpperCase()}). Refunding archives the combine this payment bought — working orders cancel, chargeback-webhook semantics.`}
          confirmLabel="Refund payment"
          confirmKind="danger"
          disabled={!hasReason}
          pending={pending}
          onConfirm={() =>
            onRun(
              () => refundPayment(modal.payment.id, reason.trim()),
              `Payment #${modal.payment.id} refunded.`,
            )
          }
        >
          {reasonField()}
        </ActionModal>
      );
    case "adjust": {
      const needsDays = adjustAction === "extend_billing";
      return (
        <ActionModal
          open
          onClose={onClose}
          title={`Adjust combine #${modal.combine.id} (${modal.combine.tier.toUpperCase()})`}
          description="fail mirrors an MLL breach; unfail restores outcome AND status to active; extend billing pushes paid-through."
          confirmLabel="Apply adjustment"
          confirmKind={adjustAction === "fail" ? "danger" : "primary"}
          disabled={!hasReason || (needsDays && (days < 1 || days > 90))}
          pending={pending}
          onConfirm={() =>
            onRun(
              () =>
                adjustCombine(modal.combine.id, {
                  action: adjustAction,
                  reason: reason.trim(),
                  ...(needsDays ? { days } : {}),
                }),
              `Combine #${modal.combine.id}: ${adjustAction.replace("_", " ")} applied.`,
            )
          }
        >
          <Field label="Action">
            <select
              value={adjustAction}
              onChange={(e) => setAdjustAction(e.target.value as CombineAdjustAction)}
              className={SELECT_CLS}
              style={{ fontSize: 12 }}
            >
              <option value="fail">Fail (manual rule breach)</option>
              <option value="unfail">Unfail (restore to active)</option>
              <option value="extend_billing">Extend billing</option>
            </select>
          </Field>
          {needsDays && (
            <Field label="Days (1–90)">
              <input
                type="number"
                min={1}
                max={90}
                value={days}
                onChange={(e) => setDays(Number(e.target.value) || 0)}
                className={`${INPUT_CLS} w-24 tabular-nums`}
                style={{ fontSize: 12 }}
              />
            </Field>
          )}
          {reasonField()}
        </ActionModal>
      );
    }
  }
}
