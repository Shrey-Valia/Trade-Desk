import { useEffect, useMemo, useRef, useState } from "react";

import { useLiquidUniverse } from "@/hooks/useLiquidUniverse";
import { useSelectedTicker } from "@/stores/selectedTicker";

const MAX_SUGGESTIONS = 8;

/**
 * Symbol search box for the Trade Desk toolbar.
 *
 * Autocompletes against the prewarmed liquid set so the user lands on a
 * warm ticker. Free-form input — any non-empty value goes through to
 * setSymbol on Enter; obscure (non-warmed) tickers cold-load.
 *
 * Keyboard:
 *   - Type to filter, ↑/↓ to move highlight, Enter to commit
 *   - Esc to close the dropdown without committing
 *   - Click a row to commit
 */
export function SymbolSearch() {
  const { data } = useLiquidUniverse();
  const setSymbol = useSelectedTicker((s) => s.setSymbol);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const universe = data?.symbols ?? [];

  const matches = useMemo(() => {
    if (!query) return [];
    const q = query.toUpperCase();
    const starts: string[] = [];
    const contains: string[] = [];
    for (const sym of universe) {
      if (sym.startsWith(q)) starts.push(sym);
      else if (sym.includes(q)) contains.push(sym);
      if (starts.length + contains.length >= MAX_SUGGESTIONS + 5) break;
    }
    return [...starts, ...contains].slice(0, MAX_SUGGESTIONS);
  }, [query, universe]);

  // Click outside closes the dropdown without committing.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const commit = (sym: string) => {
    const trimmed = sym.trim().toUpperCase();
    if (!trimmed) return;
    setSymbol(trimmed);
    setQuery("");
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const pick = matches[activeIndex] ?? query;
      commit(pick);
      return;
    }
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    }
  };

  return (
    <div ref={wrapperRef} className="relative" style={{ width: 220 }}>
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActiveIndex(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder="Search ticker..."
        spellCheck={false}
        autoComplete="off"
        className="w-full h-7 px-2 text-xs2 font-mono uppercase tracking-wide bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary placeholder:normal-case placeholder:tracking-normal"
        style={{ borderRadius: 0 }}
        aria-label="Search ticker"
        aria-autocomplete="list"
        aria-expanded={open && matches.length > 0}
      />
      {open && matches.length > 0 && (
        <ul
          role="listbox"
          className="absolute left-0 right-0 top-full mt-px z-30 bg-tier-1 border border-hairline border-t-0 max-h-64 overflow-y-auto"
        >
          {matches.map((sym, i) => (
            <li
              key={sym}
              role="option"
              aria-selected={i === activeIndex}
              onMouseDown={(e) => {
                // mousedown (not click) so the input doesn't blur first
                e.preventDefault();
                commit(sym);
              }}
              onMouseEnter={() => setActiveIndex(i)}
              className={[
                "px-2 py-1 text-xs2 cursor-pointer tabular-nums",
                i === activeIndex
                  ? "bg-tier-2 text-fg-primary"
                  : "text-fg-secondary hover:bg-tier-2",
              ].join(" ")}
            >
              {sym}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
