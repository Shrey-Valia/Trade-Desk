import { createElement, memo, useEffect } from "react";

/**
 * TradingView ships a second family of widgets as ESM modules that register
 * custom elements (e.g. <tv-ticker-tape>, <tv-economic-map>). This wrapper:
 *   1. Loads the module script once per URL (idempotent across mounts).
 *   2. Renders the custom element with the requested attributes.
 *
 * Custom elements aren't typed in JSX, so we render via React.createElement
 * with a string tag rather than fighting JSX.IntrinsicElements.
 */
type Props = {
  /** Module URL that defines the custom element. */
  scriptSrc: string;
  /** Custom element tag name, e.g. "tv-ticker-tape". */
  tag: string;
  /** HTML attributes set on the custom element. */
  attrs?: Record<string, string>;
  className?: string;
};

const loaded = new Set<string>();

function loadModuleOnce(src: string) {
  if (loaded.has(src)) return;
  loaded.add(src);
  const script = document.createElement("script");
  script.type = "module";
  script.src = src;
  document.head.appendChild(script);
}

function TradingViewWebComponentImpl({ scriptSrc, tag, attrs, className }: Props) {
  useEffect(() => {
    loadModuleOnce(scriptSrc);
  }, [scriptSrc]);

  // React 18 doesn't translate `className` → `class` on unknown custom
  // elements; the prop falls through to the DOM as literal `classname`,
  // which CSS can't target. Pass `class` directly instead.
  return createElement(tag, { ...attrs, class: className });
}

export const TradingViewWebComponent = memo(TradingViewWebComponentImpl);
