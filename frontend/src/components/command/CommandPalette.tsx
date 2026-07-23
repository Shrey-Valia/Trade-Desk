import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/ui/Modal";
import { BOTTOM_ITEMS, TOP_ITEMS } from "@/components/layout/LeftRail";
import { useCommandPalette } from "@/stores/commandPalette";
import { useHotkeyActions } from "@/stores/hotkeyActions";
import { useOnboarding } from "@/stores/onboarding";

interface Command {
  id: string;
  label: string;
  /** Extra search aliases. */
  hint?: string;
  run: () => void;
}

/**
 * Command palette (WS6) — ⌘K / Ctrl-K. Fuzzy-filtered list of navigation
 * destinations (the rail routes) plus the key actions (help, replay tour,
 * close active position, pre-arm buy/sell). Keyboard-first: ↑/↓ move the
 * selection, Enter runs it, Esc closes. Built on the accessible Modal
 * primitive (focus trap + restore-focus).
 */
export function CommandPalette() {
  const open = useCommandPalette((s) => s.open);
  const setOpen = useCommandPalette((s) => s.setOpen);
  const navigate = useNavigate();
  const setHelpOpen = useOnboarding((s) => s.setHelpOpen);
  const openTour = useOnboarding((s) => s.openTour);
  const request = useHotkeyActions((s) => s.request);

  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo<Command[]>(() => {
    const nav: Command[] = [...TOP_ITEMS, ...BOTTOM_ITEMS].map((it) => ({
      id: `nav:${it.to}`,
      label: `Go to ${it.label}`,
      hint: it.to,
      run: () => navigate(it.to),
    }));
    const actions: Command[] = [
      {
        id: "act:help",
        label: "Open help & glossary",
        hint: "? terms mll dll 0dte",
        run: () => setHelpOpen(true),
      },
      {
        id: "act:tour",
        label: "Replay the walkthrough",
        hint: "onboarding tour",
        run: () => openTour(),
      },
      {
        id: "act:close",
        label: "Close the active position",
        hint: "c exit",
        run: () => request("closeActive"),
      },
      {
        id: "act:closeall",
        label: "Close all positions (flatten)",
        hint: "flatten bulk exit all",
        // Route through the hotkey bus so the position strip's F-F arm/confirm
        // guard runs — flattening every position must never fire on a single
        // action. (First invoke arms + toasts "Press F again to FLATTEN".)
        run: () => request("flattenAll"),
      },
      {
        id: "act:buy",
        label: "Pre-arm BUY on selected contract",
        hint: "b long",
        run: () => request("armBuy"),
      },
      {
        id: "act:sell",
        label: "Pre-arm SELL on selected contract",
        hint: "s short",
        run: () => request("armSell"),
      },
    ];
    return [...nav, ...actions];
    // closeAll is recreated each render but behaviorally stable; intentionally
    // omitted from deps to keep the command list referentially steady.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setHelpOpen, openTour, request]);

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(needle) ||
        (c.hint ?? "").toLowerCase().includes(needle),
    );
  }, [q, commands]);

  // Reset query + cursor each time the palette opens.
  useEffect(() => {
    if (!open) return;
    setQ("");
    setCursor(0);
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  // Keep the cursor in range as the result set shrinks.
  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(0, results.length - 1)));
  }, [results.length]);

  const runAt = (idx: number) => {
    const cmd = results[idx];
    if (!cmd) return;
    setOpen(false);
    cmd.run();
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      labelledBy="command-palette-title"
      align="top"
      panelClassName="w-full max-w-lg bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl flex flex-col max-h-[70vh]"
    >
      <h2 id="command-palette-title" className="sr-only">
        Command palette
      </h2>
      <div className="px-3 py-2.5 border-b border-hairline shrink-0">
        <label className="sr-only" htmlFor="command-input">
          Type a command or search
        </label>
        <input
          id="command-input"
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded
          aria-controls="command-list"
          aria-activedescendant={results[cursor] ? `cmd-${results[cursor].id}` : undefined}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(results.length - 1, c + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(0, c - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              runAt(cursor);
            }
          }}
          placeholder="Type a command or search…"
          className="w-full bg-tier-2 border border-tier-3 rounded-btn px-3 py-2 text-sm text-fg-primary placeholder:text-fg-tertiary"
        />
      </div>
      <ul id="command-list" role="listbox" className="overflow-y-auto min-h-0 py-1">
        {results.length === 0 && (
          <li className="px-3 py-3 text-sm text-fg-tertiary-2">No commands match.</li>
        )}
        {results.map((c, i) => (
          <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === cursor}>
            <button
              type="button"
              onClick={() => runAt(i)}
              onMouseEnter={() => setCursor(i)}
              className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between ${
                i === cursor
                  ? "bg-tier-2 text-fg-primary"
                  : "text-fg-secondary hover:bg-tier-2"
              }`}
            >
              <span>{c.label}</span>
              {c.id.startsWith("nav:") && (
                <span className="text-tiny text-fg-tertiary-2 font-mono">{c.hint}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <div className="px-3 py-2 border-t border-hairline shrink-0 flex items-center gap-3 text-tiny text-fg-tertiary-2">
        <span>
          <kbd className="font-mono">↑↓</kbd> navigate
        </span>
        <span>
          <kbd className="font-mono">↵</kbd> run
        </span>
        <span>
          <kbd className="font-mono">esc</kbd> close
        </span>
      </div>
    </Modal>
  );
}
