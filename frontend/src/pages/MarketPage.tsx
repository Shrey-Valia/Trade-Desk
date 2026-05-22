import { TradingViewEmbed } from "@/components/tradingview/TradingViewEmbed";
import { TradingViewWebComponent } from "@/components/tradingview/TradingViewWebComponent";

const HEATMAP_CONFIG = {
  dataSource: "SPX500",
  blockSize: "market_cap_basic",
  blockColor: "change",
  grouping: "sector",
  locale: "en",
  symbolUrl: "",
  colorTheme: "dark",
  exchanges: [],
  hasTopBar: false,
  isDataSetEnabled: false,
  isZoomEnabled: true,
  hasSymbolTooltip: true,
  isMonoSize: false,
  isTransparent: true,
  width: "100%",
  height: "100%",
};

/**
 * Two-pane market overview, 65/35 vertical split.
 *   - Top 65%: S&P 500 sector heatmap (centerpiece)
 *   - Bottom 35%: global economic indicators map
 *
 * Both wrapped in hairline-bordered panels with our 9px uppercase section
 * labels — gives the TradingView widgets a "panel within the terminal"
 * frame, so foreign typography reads as ambient context not chrome.
 */
export function MarketPage() {
  return (
    <div className="flex flex-col flex-1 min-h-0 bg-tier-0 p-2 gap-2">
      <Panel title="S&P 500 Heatmap" subtitle="Mkt-cap weighted · sector grouped" className="flex-[65]">
        <TradingViewEmbed
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js"
          config={HEATMAP_CONFIG}
        />
      </Panel>
      <Panel title="Global Economic Indicators" subtitle="GDP · Inflation · Rates · Debt" className="flex-[35]">
        <div className="economic-map-frame h-full w-full">
          <TradingViewWebComponent
            scriptSrc="https://widgets.tradingview-widget.com/w/en/tv-economic-map.js"
            tag="tv-economic-map"
            className="block h-full w-full"
            attrs={{
              "color-theme": "dark",
              "is-transparent": "true",
            }}
          />
        </div>
      </Panel>
    </div>
  );
}

function Panel({
  title,
  subtitle,
  className,
  children,
}: {
  title: string;
  subtitle: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`flex flex-col min-h-0 border border-hairline bg-tier-0 ${className ?? ""}`}>
      <div className="flex items-baseline gap-3 px-3 py-1.5 border-b border-hairline shrink-0">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">{title}</span>
        <span className="text-tiny text-fg-tertiary">{subtitle}</span>
      </div>
      <div className="flex-1 min-h-0 widget-clip">{children}</div>
    </section>
  );
}
