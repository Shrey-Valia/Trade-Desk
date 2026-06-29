import { useEffect, useRef, type ReactNode } from "react";

/**
 * Accessible modal dialog primitive (WS6 a11y).
 *
 * Provides the three things every overlay in the app needs and that the
 * older bespoke modals each re-implemented (or skipped):
 *   - a backdrop that closes on outside-click,
 *   - Escape-to-close,
 *   - a FOCUS TRAP: focus moves into the dialog on open, Tab/Shift-Tab
 *     cycle within it, and focus is restored to the previously-focused
 *     element on close.
 *
 * role="dialog" + aria-modal="true" + aria-labelledby wire the title to
 * assistive tech. Pass a stable `titleId` and render a heading with that
 * id inside `children` (or use the optional `title` prop for the common
 * case of a simple text heading).
 */
interface Props {
  open: boolean;
  onClose: () => void;
  /** id the dialog is labelled by — must match a heading rendered inside. */
  labelledBy: string;
  children: ReactNode;
  /** Extra classes on the dialog panel (sizing/positioning). */
  panelClassName?: string;
  /** Alignment of the panel within the viewport. Default centers it. */
  align?: "center" | "top";
}

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function Modal({
  open,
  onClose,
  labelledBy,
  children,
  panelClassName = "",
  align = "center",
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const prevFocus = document.activeElement as HTMLElement | null;

    // Move focus into the dialog — the first focusable, else the panel.
    const focusFirst = () => {
      const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? panel)?.focus();
    };
    const raf = window.requestAnimationFrame(focusFirst);

    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      // Focus trap: keep Tab cycling inside the panel.
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKey, true);
    return () => {
      window.cancelAnimationFrame(raf);
      document.removeEventListener("keydown", handleKey, true);
      // Restore focus to the trigger so keyboard users aren't dumped at
      // the top of the page.
      prevFocus?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const alignClass = align === "top" ? "items-start pt-[12vh]" : "items-center";

  return (
    <div
      className={`fixed inset-0 z-50 flex justify-center px-4 ${alignClass} bg-black/60`}
      onMouseDown={(e) => {
        // Outside-click closes; clicks inside the panel are swallowed by
        // the panel's own stopPropagation below.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={`outline-none ${panelClassName}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
