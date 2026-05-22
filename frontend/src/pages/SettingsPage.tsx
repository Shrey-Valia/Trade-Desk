import { PageHeader } from "@/components/layout/PageHeader";

/**
 * Settings stub — Step 1 of the navigation revamp.
 *
 * Real content (theme, broker connection, data sources, mistake-tag
 * vocabulary editor, …) is deferred to a later step. This route exists
 * so the left rail's gear destination has somewhere to land instead
 * of a 404.
 */
export function SettingsPage() {
  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Settings" />
      <main className="flex-1 min-h-0 flex items-center justify-center border-t border-hairline">
        <div className="text-center">
          <div className="text-tiny uppercase tracking-label-up text-fg-tertiary mb-1"
               style={{ fontSize: 9 }}>
            Settings
          </div>
          <div className="text-xs2 text-fg-secondary">Coming soon</div>
          <div className="text-tiny text-fg-tertiary mt-2 max-w-sm" style={{ fontSize: 10 }}>
            Theme, broker connection, data sources, mistake-tag vocabulary
          </div>
        </div>
      </main>
    </div>
  );
}
