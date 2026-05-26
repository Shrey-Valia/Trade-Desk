import type { WatchlistItem as Item } from "@/types/watchlist";

interface Props {
  item: Item;
  selected?: boolean;
  onSelect?: (symbol: string) => void;
}

/**
 * Sparse watchlist row — TradingView/Topstep aesthetic.
 *
 *   AAPL                       182.43   +1.23%
 *
 * One ticker = one tight row: symbol + price + signed change%. No news
 * subtitle, no logo, no third-party widget. The aim is a calm scannable
 * column of symbols, not a feed of news cards.
 *
 * Selected state lives on the row container: amber left rule + bg-tier-2.
 * IBM Plex Mono, tabular-nums on every number per DESIGN.md.
 */
export function WatchlistItem({ item, selected = false, onSelect }: Props) {
  const onClick = () => onSelect?.(item.symbol);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };
  const positive = item.change_pct >= 0;
  const changeClass = positive ? "text-bullish" : "text-bearish";
  const changeSign = positive ? "+" : "";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={onKeyDown}
      aria-pressed={selected}
      aria-label={`${item.symbol} ${item.price.toFixed(2)} ${changeSign}${item.change_pct.toFixed(2)} percent`}
      className={[
        "flex items-baseline justify-between gap-2 px-3 py-1 text-tiny cursor-pointer transition-opacity duration-100 border-l-2",
        selected
          ? "border-l-amber bg-tier-2"
          : "border-l-transparent hover:bg-tier-2",
      ].join(" ")}
    >
      <span
        className={
          selected ? "text-amber" : "text-fg-primary"
        }
      >
        {item.symbol}
      </span>
      <span className="flex items-baseline gap-2 tabular-nums">
        <span className="text-fg-primary">{formatPrice(item.price)}</span>
        <span
          className={`${changeClass}`}
          style={{ minWidth: 56, textAlign: "right" }}
        >
          {changeSign}
          {item.change_pct.toFixed(2)}%
        </span>
      </span>
    </div>
  );
}

function formatPrice(p: number): string {
  if (!Number.isFinite(p)) return "—";
  // Tight 2dp formatting; large prices already read well in monospace.
  return p.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
