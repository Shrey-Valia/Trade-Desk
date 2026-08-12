import { Navigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { useMe } from "@/hooks/useAuth";

import { AdminAudit } from "./AdminAudit";
import { AdminInvites } from "./AdminInvites";
import { AdminJobs } from "./AdminJobs";
import { AdminOverview } from "./AdminOverview";
import { AdminPayoutQueue } from "./AdminPayoutQueue";
import { AdminPlatform } from "./AdminPlatform";
import { AdminSupport } from "./AdminSupport";
import { AdminUsers } from "./AdminUsers";

/**
 * Operator console root (workstream D1). Role-gated client-side for UX
 * only — the real enforcement is require_admin on every /api/admin
 * endpoint. Sections live behind ?tab= (deep-linkable, back-button
 * friendly) and share the instrument-cluster vocabulary from ./adminUi.
 */

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "payouts", label: "Payouts" },
  { key: "users", label: "Users" },
  { key: "invites", label: "Invites" },
  { key: "platform", label: "Platform" },
  { key: "support", label: "Support" },
  { key: "jobs", label: "Jobs" },
  { key: "audit", label: "Audit" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export function AdminPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();

  if (me.isPending) return <div className="min-h-screen bg-tier-0" />;
  if (!me.isSuccess || me.data.role !== "admin") {
    return <Navigate to="/dashboard" replace />;
  }

  const raw = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === raw)
    ? (raw as TabKey)
    : "overview";

  const setTab = (next: TabKey) => {
    setParams(next === "overview" ? {} : { tab: next }, { replace: false });
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Operator console" subtitle="Admin-only back office" />
      <nav
        aria-label="Admin sections"
        className="flex items-stretch gap-0 border-b border-hairline bg-tier-0 px-3.5 shrink-0 overflow-x-auto"
      >
        {TABS.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              aria-current={active ? "page" : undefined}
              className={[
                "relative px-3 py-2 uppercase tracking-label-up whitespace-nowrap",
                "transition-colors duration-100",
                active
                  ? "text-amber"
                  : "text-fg-tertiary-2 hover:text-fg-primary",
              ].join(" ")}
              style={{ fontSize: 12 }}
            >
              {t.label}
              {active && (
                <span
                  aria-hidden
                  className="absolute left-0 right-0 bottom-0 bg-amber"
                  style={{ height: 2 }}
                />
              )}
            </button>
          );
        })}
      </nav>
      <main className="flex-1 min-h-0 overflow-y-auto">
        <div className="mx-auto w-full p-3.5" style={{ maxWidth: 1280 }}>
          {tab === "overview" && <AdminOverview />}
          {tab === "payouts" && <AdminPayoutQueue />}
          {tab === "users" && <AdminUsers />}
          {tab === "invites" && <AdminInvites />}
          {tab === "platform" && <AdminPlatform />}
          {tab === "support" && <AdminSupport />}
          {tab === "jobs" && <AdminJobs />}
          {tab === "audit" && <AdminAudit />}
        </div>
      </main>
    </div>
  );
}
