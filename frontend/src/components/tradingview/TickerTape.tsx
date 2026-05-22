import { TradingViewWebComponent } from "./TradingViewWebComponent";

/**
 * Persistent ticker tape strip. Pinned at the very top of every page so
 * the user always sees SPX/NDX/DJI + EUR/USD + BTC/ETH + Gold scrolling.
 *
 * `widget-clip-strip` trims a few pixels off the bottom — TradingView's
 * loader sometimes inserts a 1-2px footer rule that would otherwise
 * bleed into our hairline below.
 */
export function TickerTape() {
  return (
    <div className="border-b border-hairline bg-tier-0 widget-clip-strip">
      <TradingViewWebComponent
        scriptSrc="https://widgets.tradingview-widget.com/w/en/tv-ticker-tape.js"
        tag="tv-ticker-tape"
        attrs={{
          symbols:
            "FOREXCOM:SPXUSD,FOREXCOM:NSXUSD,FOREXCOM:DJI,FX:EURUSD,BITSTAMP:BTCUSD,BITSTAMP:ETHUSD,CMCMARKETS:GOLD",
          "is-transparent": "true",
          "color-theme": "dark",
        }}
      />
    </div>
  );
}
