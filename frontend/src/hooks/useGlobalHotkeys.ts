import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { useCommandPalette } from "@/stores/commandPalette";
import { useHotkeyActions } from "@/stores/hotkeyActions";
import { useOnboarding } from "@/stores/onboarding";

/**
 * Global keyboard shortcuts (WS6 power-UX). Mounted once in the authed shell.
 *
 *   ⌘K / Ctrl-K  command palette (navigate + actions)
 *   ?            help / glossary overlay
 *   B            pre-arm BUY on the selected contract
 *   S            pre-arm SELL on the selected contract
 *   C            close the active position (press twice to confirm)
 *   F            flatten ALL positions (press twice to confirm)
 *   X            cancel ALL working orders (press twice to confirm)
 *
 * Single-letter keys are ignored while the user is typing in an input,
 * textarea, or contenteditable, and whenever a modifier is held, so they
 * never swallow a real keystroke. (Symbol search "/" + ⌘K-for-search live in
 * TradeDeskHeader; this hook owns ⌘K for the palette — the palette's first
 * entry IS symbol search, so nothing is lost.)
 */
export function useGlobalHotkeys() {
  const togglePalette = useCommandPalette((s) => s.toggle);
  const toggleHelp = useOnboarding((s) => s.toggleHelp);
  const request = useHotkeyActions((s) => s.request);
  const clearIntent = useHotkeyActions((s) => s.clear);

  // Intent hygiene: a pending intent must never survive a route change and
  // replay on whatever consumer mounts on the next page.
  const { pathname } = useLocation();
  useEffect(() => {
    clearIntent();
  }, [pathname, clearIntent]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName ?? "";
      const isEditable =
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        t?.isContentEditable === true;

      // ⌘K / Ctrl-K — command palette. Works even from an input.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        togglePalette();
        return;
      }

      // Single-letter / "?" shortcuts: skip while typing or with a modifier.
      if (isEditable || e.metaKey || e.ctrlKey || e.altKey) return;

      switch (e.key) {
        case "?":
          e.preventDefault();
          toggleHelp();
          break;
        case "b":
        case "B":
          e.preventDefault();
          request("armBuy");
          break;
        case "s":
        case "S":
          e.preventDefault();
          request("armSell");
          break;
        case "c":
        case "C":
          e.preventDefault();
          request("closeActive");
          break;
        case "f":
        case "F":
          e.preventDefault();
          request("flattenAll");
          break;
        case "x":
        case "X":
          e.preventDefault();
          request("cancelAllOrders");
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePalette, toggleHelp, request]);
}
