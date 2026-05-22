import { TradingViewWebComponent } from "@/components/tradingview/TradingViewWebComponent";
import type { WatchlistItem as Item } from "@/types/watchlist";

interface Props {
  item: Item;
  selected?: boolean;
  onSelect?: (symbol: string) => void;
}

// Most of our universe trades on NASDAQ; map the NYSE-listed ones explicitly.
// Falling back to bare symbol works on TradingView too, but the prefix gives
// the Ticker Tag deterministic resolution and skips its disambiguation step.
const EXCHANGE_PREFIX: Record<string, string> = {
  BA: "NYSE",
  F: "NYSE",
  SPY: "AMEX",
};

function tickerTagSymbol(sym: string): string {
  const prefix = EXCHANGE_PREFIX[sym] ?? "NASDAQ";
  return `${prefix}:${sym}`;
}

/**
 * Watchlist row — Ticker Tag pill + our subtitle.
 *
 * The pill is TradingView's web component, so its font + colors are
 * TradingView's (we don't get to brand inside the iframe). We wrap it
 * with `pointer-events: none` so the pill stays decorative: hover-preview
 * and click-through to TradingView.com both go away, and the entire row
 * becomes one click target that selects the ticker locally. This is a
 * deliberate trade against the built-in mini-chart hover preview — the
 * row's selection behavior matters more than a TradingView popover.
 *
 * Selected state lives on the row container (amber left rule + tier-2
 * elevation) so it visually frames the foreign pill without touching it.
 */
export function WatchlistItem({ item, selected = false, onSelect }: Props) {
  const onClick = () => onSelect?.(item.symbol);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={onKeyDown}
      aria-pressed={selected}
      aria-label={`${item.symbol}. ${item.subtitle}`}
      className={[
        "w-full px-3 py-1.5 text-left cursor-pointer transition-opacity duration-100 border-l-2",
        selected
          ? "border-l-amber bg-tier-2"
          : "border-l-transparent hover:bg-tier-2",
      ].join(" ")}
    >
      <div className="pointer-events-none">
        <TradingViewWebComponent
          scriptSrc="https://widgets.tradingview-widget.com/w/en/tv-ticker-tag.js"
          tag="tv-ticker-tag"
          attrs={{
            symbol: tickerTagSymbol(item.symbol),
            theme: "dark",
            "is-transparent": "true",
            "display-mode": "adaptive",
          }}
        />
      </div>
      <div className="text-tiny text-fg-tertiary truncate mt-0.5">{item.subtitle}</div>
    </div>
  );
}
