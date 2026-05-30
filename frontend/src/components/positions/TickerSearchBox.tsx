import { useEffect, useRef, useState } from "react";

import { useTickerSearch } from "@/hooks/useTickerSearch";
import type { SearchHit } from "@/types/search";

interface Props {
  symbol: string | null;
  onSelect: (sym: string) => void;
}

/**
 * Header search box that replaces the SPY/QQQ/IWM hard switcher.
 *
 * - 200×36 input with a magnifying-glass icon, "Search ticker..."
 *   placeholder, 4px radius. Focus state: amber border.
 * - 1+ character → debounced query to /api/ticker/search.
 * - Dropdown lists up to 10 matches. Each row: ticker (left),
 *   company name (middle, fg-tertiary), "0DTE TODAY" amber-outline
 *   badge or quiet "no 0DTE today" label on the right.
 * - Selecting a row fires onSelect(symbol) and closes the menu.
 * - Esc closes; click-outside closes.
 *
 * If a non-0DTE ticker is selected, the chain will surface the
 * existing "no 0DTE for SYMBOL today" panel-level message — the
 * search doesn't gate the selection itself.
 */
export function TickerSearchBox({ symbol, onSelect }: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data, isFetching } = useTickerSearch(q);
  const results = data?.results ?? [];

  // Click-outside closes the dropdown without clobbering the symbol.
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("mousedown", handle);
    return () => window.removeEventListener("mousedown", handle);
  }, []);

  const pick = (hit: SearchHit) => {
    onSelect(hit.symbol);
    setQ("");
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className="relative" ref={wrapRef} style={{ width: 220 }}>
      <div className="relative">
        <span
          aria-hidden
          className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-tertiary-2"
          style={{ fontSize: 12 }}
        >
          ⌕
        </span>
        <input
          ref={inputRef}
          type="text"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              inputRef.current?.blur();
            }
            if (e.key === "Enter" && results[0]) {
              pick(results[0]);
            }
          }}
          placeholder={
            symbol ? `${symbol} · search ticker…` : "Search ticker…"
          }
          spellCheck={false}
          autoComplete="off"
          aria-label="Search ticker"
          className={[
            "h-9 w-full pl-7 pr-3 bg-tier-2 border rounded-btn",
            "text-fg-primary placeholder:text-fg-tertiary-2",
            "border-tier-3 focus:border-amber focus:outline-none",
            "font-mono tabular-nums",
          ].join(" ")}
          style={{ fontSize: 13 }}
        />
      </div>
      {open && q.trim().length > 0 && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1 z-40 bg-tier-2 border border-tier-3 rounded-btn overflow-hidden"
          style={{ width: "100%", minWidth: 280 }}
        >
          {results.length === 0 && (
            <div className="px-3 py-2 text-tiny text-fg-tertiary-2">
              {isFetching ? "Searching…" : "No matches."}
            </div>
          )}
          {results.map((hit) => (
            <button
              key={hit.symbol}
              type="button"
              onClick={() => pick(hit)}
              className={[
                "w-full text-left px-3 py-1.5 flex items-baseline gap-2",
                "hover:bg-tier-3 focus:bg-tier-3 outline-none",
                hit.symbol === symbol ? "bg-tier-3" : "",
              ].join(" ")}
              style={{ fontSize: 13 }}
            >
              <span className="text-fg-primary tabular-nums font-medium">
                {hit.symbol}
              </span>
              <span className="text-fg-tertiary-2 truncate flex-1" style={{ fontSize: 11 }}>
                {hit.name}
              </span>
              {hit.has_0dte_today ? (
                <span
                  className="inline-flex items-center border border-amber text-amber px-1.5 uppercase tracking-label-up rounded-btn shrink-0"
                  style={{ fontSize: 9, height: 16 }}
                >
                  0DTE today
                </span>
              ) : (
                <span
                  className="text-fg-tertiary-2 shrink-0"
                  style={{ fontSize: 9 }}
                >
                  no 0DTE today
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
