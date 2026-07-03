import { useMemo, useState } from "react";

import { Modal } from "@/components/ui/Modal";
import { GLOSSARY } from "@/lib/glossary";
import { useOnboarding } from "@/stores/onboarding";

/** Hotkey reference — kept in sync with useGlobalHotkeys + the palette. */
const HOTKEYS: Array<{ keys: string; action: string }> = [
  { keys: "?", action: "Open this help / glossary" },
  { keys: "⌘K / Ctrl-K", action: "Command palette (navigate + actions)" },
  { keys: "/", action: "Symbol search" },
  { keys: "B", action: "Pre-arm BUY on the selected contract" },
  { keys: "S", action: "Pre-arm SELL on the selected contract" },
  { keys: "C C", action: "Close the active position (press twice to confirm)" },
  { keys: "F F", action: "FLATTEN all open positions (press twice to confirm)" },
  { keys: "X X", action: "Cancel all working orders (press twice to confirm)" },
  { keys: "Esc", action: "Close any overlay" },
];

/**
 * Help / glossary overlay (WS6). A searchable list of the key prop-firm
 * and options terms (MLL, DLL, combine, 0DTE, greeks, …) plus the global
 * hotkey reference. Opened by "?", the command palette, or "Replay tour".
 *
 * Reuses the accessible Modal primitive (focus trap + Esc + restore-focus),
 * so this overlay is keyboard-operable and screen-reader-labelled for free.
 */
export function HelpOverlay() {
  const open = useOnboarding((s) => s.helpOpen);
  const setHelpOpen = useOnboarding((s) => s.setHelpOpen);
  const openTour = useOnboarding((s) => s.openTour);
  const [q, setQ] = useState("");

  const terms = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return GLOSSARY;
    return GLOSSARY.filter(
      (t) =>
        t.term.toLowerCase().includes(needle) ||
        (t.full ?? "").toLowerCase().includes(needle) ||
        t.definition.toLowerCase().includes(needle),
    );
  }, [q]);

  return (
    <Modal
      open={open}
      onClose={() => setHelpOpen(false)}
      labelledBy="help-overlay-title"
      align="top"
      panelClassName="w-full max-w-2xl bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl flex flex-col max-h-[80vh]"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-hairline shrink-0">
        <h2
          id="help-overlay-title"
          className="text-medium font-medium text-fg-primary"
        >
          Help &amp; glossary
        </h2>
        <button
          type="button"
          onClick={() => setHelpOpen(false)}
          aria-label="Close help"
          className="text-medium leading-none text-fg-secondary hover:text-fg-primary px-1"
        >
          ×
        </button>
      </div>

      <div className="px-4 py-3 border-b border-hairline shrink-0">
        <label className="sr-only" htmlFor="help-search">
          Search glossary
        </label>
        <input
          id="help-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search terms…"
          className="w-full bg-tier-2 border border-tier-3 rounded-btn px-3 py-2 text-sm text-fg-primary placeholder:text-fg-tertiary"
        />
      </div>

      <div className="overflow-y-auto px-4 py-3 min-h-0">
        <h3 className="text-tiny uppercase tracking-label-up text-fg-secondary mb-2">
          Key terms
        </h3>
        <dl className="flex flex-col gap-3">
          {terms.length === 0 && (
            <p className="text-sm text-fg-tertiary-2">No terms match “{q}”.</p>
          )}
          {terms.map((t) => (
            <div key={t.term}>
              <dt className="text-sm font-medium text-fg-primary">
                {t.term}
                {t.full && (
                  <span className="text-fg-tertiary-2 font-normal"> · {t.full}</span>
                )}
              </dt>
              <dd className="text-sm text-fg-secondary leading-snug mt-0.5">
                {t.definition}
              </dd>
            </div>
          ))}
        </dl>

        <h3 className="text-tiny uppercase tracking-label-up text-fg-secondary mt-5 mb-2">
          Keyboard shortcuts
        </h3>
        <ul className="flex flex-col gap-1.5">
          {HOTKEYS.map((h) => (
            <li key={h.keys} className="flex items-baseline gap-3 text-sm">
              <kbd
                className="shrink-0 min-w-[88px] text-center border border-tier-3 bg-tier-2 rounded-btn px-1.5 py-0.5 font-mono text-fg-primary"
                style={{ fontSize: 12 }}
              >
                {h.keys}
              </kbd>
              <span className="text-fg-secondary">{h.action}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex items-center justify-between px-4 py-3 border-t border-hairline shrink-0">
        <button
          type="button"
          onClick={() => {
            setHelpOpen(false);
            openTour();
          }}
          className="text-sm text-cyan hover:underline"
        >
          Replay the walkthrough
        </button>
        <button
          type="button"
          onClick={() => setHelpOpen(false)}
          className="bg-tier-2 border border-tier-3 hover:bg-tier-3 rounded-btn px-3 py-1.5 text-sm text-fg-primary"
        >
          Done
        </button>
      </div>
    </Modal>
  );
}
