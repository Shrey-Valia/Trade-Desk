import { useEffect, useMemo, useRef, useState } from "react";

import {
  logSelection,
  usePopularTickers,
  useStars,
  useToggleStar,
} from "@/hooks/useSymbolBrowse";
import { useTickerSearch } from "@/hooks/useTickerSearch";

interface Props {
  open: boolean;
  /** Currently-active ticker — used to highlight the matching row. */
  activeSymbol: string | null;
  onSelect: (symbol: string) => void;
  onClose: () => void;
}

/**
 * Symbol search modal — STARRED + POPULAR + SEARCH RESULTS.
 *
 * Layout (top to bottom):
 *   1. header  (title + close X)
 *   2. search input (autofocused on open)
 *   3. STARRED section, only when stars.length > 0
 *   4. POPULAR section, always visible (curated 8 names)
 *   5. SEARCH RESULTS, only when the user has typed
 *
 * Clicking a row → onSelect(symbol) → closes modal → fires the
 * fire-and-forget POST /api/ticker/selection so the dormant
 * "algorithmic popular" feed accrues signal.
 *
 * Clicking the star icon toggles the star without closing the modal —
 * the optimistic-update hook flips the icon immediately.
 *
 * The starred and popular sections stay visible during search, per
 * spec: search results appear as a third section below them.
 */
export function SymbolSearchModal({
  open,
  activeSymbol,
  onSelect,
  onClose,
}: Props) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const { data: starsData } = useStars();
  const stars = useMemo(() => starsData?.symbols ?? [], [starsData]);
  const { data: popularData } = usePopularTickers();
  const popular = popularData?.results ?? [];
  const { data: searchData, isFetching: searchFetching } = useTickerSearch(q);
  const searchResults = searchData?.results ?? [];

  const toggleStar = useToggleStar();
  const starred = useMemo(() => new Set(stars), [stars]);

  // Reset the query and focus the input each time the modal opens so
  // a re-open doesn't surface a stale typed-in-but-not-cleared query.
  useEffect(() => {
    if (!open) return;
    setQ("");
    // Defer focus to the next tick — focusing during the same render
    // race-conditions against React mounting the input.
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  // Esc closes the modal. The keydown listener is window-scoped so the
  // user doesn't need to have the input focused for it to fire.
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [open, onClose]);

  if (!open) return null;

  const handlePick = (symbol: string): void => {
    onSelect(symbol);
    logSelection(symbol);
    onClose();
  };

  const trimmed = q.trim();
  const showSearchSection = trimmed.length > 0;

  // Build the starred-section rows. The /api/user/stars endpoint
  // returns symbols only — we resolve names from the popular slate
  // (or search-cache fallback) so each row can render a company
  // name without an extra round-trip.
  const nameLookup = new Map<string, { name: string; has0dte: boolean }>();
  for (const p of popular) {
    nameLookup.set(p.symbol, {
      name: p.name,
      has0dte: p.has_0dte_today,
    });
  }
  for (const s of searchResults) {
    if (!nameLookup.has(s.symbol)) {
      nameLookup.set(s.symbol, {
        name: s.name,
        has0dte: s.has_0dte_today,
      });
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Symbol search"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/80"
      style={{ paddingTop: "8vh" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="bg-tier-1 border border-hairline flex flex-col"
        style={{
          width: "92%",
          maxWidth: 600,
          maxHeight: "70vh",
          borderRadius: 8,
        }}
      >
        <header
          className="flex items-center justify-between px-3 py-2 border-b border-hairline shrink-0"
        >
          <span
            className="uppercase tracking-label-up text-fg-secondary"
            style={{ fontSize: 11, letterSpacing: "0.08em" }}
          >
            Symbol Search
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-fg-tertiary-2 hover:text-fg-primary"
            style={{ fontSize: 16, lineHeight: 1 }}
          >
            ×
          </button>
        </header>

        <div className="px-3 py-2 border-b border-hairline shrink-0">
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search ticker…"
            spellCheck={false}
            autoComplete="off"
            aria-label="Search ticker"
            className={[
              "w-full h-10 px-3 bg-tier-2 border rounded-btn",
              "text-fg-primary placeholder:text-fg-tertiary-2",
              "border-tier-3 focus:border-amber focus:outline-none",
              "font-mono tabular-nums",
            ].join(" ")}
            style={{ fontSize: 14 }}
          />
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
          {stars.length > 0 && (
            <Section label="Starred">
              {stars.map((sym) => {
                const meta = nameLookup.get(sym);
                return (
                  <Row
                    key={`star-${sym}`}
                    symbol={sym}
                    name={meta?.name ?? ""}
                    has0dte={meta?.has0dte ?? false}
                    starred={true}
                    isActive={sym === activeSymbol}
                    onPick={() => handlePick(sym)}
                    onToggleStar={() =>
                      toggleStar.mutate({
                        symbol: sym,
                        currentlyStarred: true,
                      })
                    }
                  />
                );
              })}
            </Section>
          )}

          <Section label="Popular">
            {popular.map((p) => (
              <Row
                key={`pop-${p.symbol}`}
                symbol={p.symbol}
                name={p.name}
                has0dte={p.has_0dte_today}
                starred={starred.has(p.symbol)}
                isActive={p.symbol === activeSymbol}
                onPick={() => handlePick(p.symbol)}
                onToggleStar={() =>
                  toggleStar.mutate({
                    symbol: p.symbol,
                    currentlyStarred: starred.has(p.symbol),
                  })
                }
              />
            ))}
          </Section>

          {showSearchSection && (
            <Section label="Search Results">
              {searchFetching && searchResults.length === 0 && (
                <EmptyHint text="Searching…" />
              )}
              {!searchFetching && searchResults.length === 0 && (
                <EmptyHint
                  text={`No 0DTE-tradeable symbol matches '${trimmed}'.`}
                />
              )}
              {searchResults.map((h) => (
                <Row
                  key={`res-${h.symbol}`}
                  symbol={h.symbol}
                  name={h.name}
                  has0dte={h.has_0dte_today}
                  starred={starred.has(h.symbol)}
                  isActive={h.symbol === activeSymbol}
                  onPick={() => handlePick(h.symbol)}
                  onToggleStar={() =>
                    toggleStar.mutate({
                      symbol: h.symbol,
                      currentlyStarred: starred.has(h.symbol),
                    })
                  }
                />
              ))}
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section + Row + Star
// ---------------------------------------------------------------------------

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-4 last:mb-0">
      <div
        className="uppercase tracking-label-up text-fg-tertiary mb-2"
        style={{ fontSize: 12, letterSpacing: "0.1em" }}
      >
        {label}
      </div>
      <div className="flex flex-col">{children}</div>
    </section>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div
      className="text-fg-tertiary-2 px-3 py-2"
      style={{ fontSize: 11 }}
    >
      {text}
    </div>
  );
}

interface RowProps {
  symbol: string;
  name: string;
  has0dte: boolean;
  starred: boolean;
  isActive: boolean;
  onPick: () => void;
  onToggleStar: () => void;
}

function Row({
  symbol,
  name,
  has0dte,
  starred,
  isActive,
  onPick,
  onToggleStar,
}: RowProps) {
  return (
    <div
      className={[
        "flex items-center gap-3 px-3 hover:bg-tier-2 transition-colors duration-75",
        isActive ? "bg-tier-3" : "",
      ].join(" ")}
      style={{ height: 36 }}
    >
      <button
        type="button"
        onClick={onToggleStar}
        aria-label={starred ? `Unstar ${symbol}` : `Star ${symbol}`}
        title={starred ? "Unstar" : "Star"}
        className="shrink-0 hover:opacity-100 transition-transform duration-200 active:scale-90"
        style={{ opacity: starred ? 1 : 0.55 }}
      >
        <StarIcon filled={starred} />
      </button>
      <button
        type="button"
        onClick={onPick}
        className="flex items-baseline gap-3 flex-1 min-w-0 text-left"
      >
        <span
          className="text-fg-primary font-mono tabular-nums font-medium shrink-0"
          style={{ fontSize: 13, width: 56 }}
        >
          {symbol}
        </span>
        <span
          className="text-fg-tertiary-2 truncate flex-1"
          style={{ fontSize: 11 }}
        >
          {name}
        </span>
        {has0dte && (
          <span
            className="inline-flex items-center border border-amber text-amber px-1.5 uppercase tracking-label-up rounded-btn shrink-0"
            style={{ fontSize: 12, height: 16 }}
          >
            0DTE today
          </span>
        )}
      </button>
    </div>
  );
}

/**
 * Inline star SVG. Lucide-react isn't in our dependency set; one
 * 14x14 path is cheaper than adding an icon library for a single
 * glyph. Filled state uses the amber accent (#F5B45A).
 */
function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill={filled ? "#F5B45A" : "none"}
      stroke={filled ? "#F5B45A" : "currentColor"}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}
