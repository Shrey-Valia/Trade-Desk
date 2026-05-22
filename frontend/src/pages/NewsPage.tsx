import { TradingViewEmbed } from "@/components/tradingview/TradingViewEmbed";

const TIMELINE_CONFIG = {
  displayMode: "regular",
  feedMode: "all_symbols",
  colorTheme: "dark",
  isTransparent: true,
  locale: "en",
  width: "100%",
  height: "100%",
};

const EVENTS_CONFIG = {
  colorTheme: "dark",
  isTransparent: true,
  locale: "en",
  countryFilter: "ar,au,br,ca,cn,fr,de,in,id,it,jp,kr,mx,ru,sa,za,tr,gb,us,eu",
  importanceFilter: "-1,0,1",
  width: "100%",
  height: "100%",
};

/**
 * 50/50 horizontal split. Each panel fills the route's available height
 * (viewport minus tape + status + nav). News items / events scroll inside
 * the iframe — our wrapper is fixed-height so the panels never push the
 * page taller than the viewport.
 */
export function NewsPage() {
  return (
    <div className="flex flex-1 min-h-0 bg-tier-0 p-2 gap-2">
      <Panel title="Top Stories" subtitle="All symbols">
        <TradingViewEmbed
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-timeline.js"
          config={TIMELINE_CONFIG}
        />
      </Panel>
      <Panel title="Economic Calendar" subtitle="Global · all importance levels">
        <TradingViewEmbed
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-events.js"
          config={EVENTS_CONFIG}
        />
      </Panel>
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col flex-1 min-w-0 min-h-0 border border-hairline bg-tier-0">
      <div className="flex items-baseline gap-3 px-3 py-1.5 border-b border-hairline shrink-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">{title}</span>
        <span className="text-tiny text-fg-tertiary">{subtitle}</span>
      </div>
      <div className="flex-1 min-h-0 widget-clip">{children}</div>
    </section>
  );
}
