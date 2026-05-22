import { memo, useEffect, useRef } from "react";

/**
 * Generic wrapper for TradingView's embed-widget scripts.
 *
 * TradingView's convention is to drop a <script> tag whose `src` is the
 * widget loader and whose `innerHTML` is a JSON config blob — the loader
 * reads the inner text on parse and injects an iframe into the
 * `.tradingview-widget-container__widget` element.
 *
 * Attribution: TradingView's TOS requires the attribution to be present
 * in the rendered iframe (which is unaffected here). We deliberately
 * don't render the optional outside-the-iframe `.tradingview-widget-
 * copyright` line — the panel wrapper that hosts this component applies
 * `.widget-clip` (see index.css) which clips ~24px off the bottom of
 * the iframe to hide the visible attribution strip.
 */
type Props = {
  scriptSrc: string;
  config: Record<string, unknown>;
  className?: string;
};

function TradingViewEmbedImpl({ scriptSrc, config, className }: Props) {
  const widgetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = widgetRef.current;
    if (!host) return;

    const script = document.createElement("script");
    script.src = scriptSrc;
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify(config);
    host.appendChild(script);

    return () => {
      host.innerHTML = "";
    };
  }, [scriptSrc, config]);

  return (
    <div className={`tradingview-widget-container h-full w-full ${className ?? ""}`}>
      <div
        ref={widgetRef}
        className="tradingview-widget-container__widget h-full w-full"
      />
    </div>
  );
}

export const TradingViewEmbed = memo(TradingViewEmbedImpl);
