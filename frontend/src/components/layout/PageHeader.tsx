import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";

/**
 * Minimal page header for the non-chart rail-shell routes (Journal /
 * Watchlist / Settings). Mirrors the 36px height + bg-tier-0 + hairline
 * bottom of TradeDeskToolbar so the visual frame stays consistent
 * across the rail's destinations even though chart-only chrome
 * (search, timeframe) is absent here.
 */
export function PageHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <header
      className="flex items-center gap-6 border-b border-hairline bg-tier-0 px-3.5 shrink-0"
      style={{ height: 36 }}
    >
      <TradeDeskLogo size="compact" />
      {/* a11y (WS6): the page title is the document's <h1> so screen-reader
          users get a heading landmark on every rail route — styling is
          unchanged (h1 default size/margins reset by the utility classes). */}
      <h1 className="text-xs2 uppercase tracking-label-up text-fg-secondary font-normal m-0">
        {title}
      </h1>
      {subtitle && (
        <span className="text-tiny text-fg-tertiary normal-case">{subtitle}</span>
      )}
    </header>
  );
}
