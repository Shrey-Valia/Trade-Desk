import { TradeDeskMark } from "@/components/branding/TradeDeskMark";

/**
 * Desktop-only gate (P2, UI simplicity audit).
 *
 * The terminal — a dense multi-panel chart + option chain + trade ticket —
 * doesn't fit a phone: below `md` the trade panel collapses, the header
 * overflows, and the nav crams. Rather than ship a broken layout, small
 * screens get this honest full-screen notice instead of the app shell.
 *
 * Pure CSS visibility (`md:hidden`), so it costs no JS and never flickers:
 * the shell itself is `hidden md:flex`, so exactly one of the two shows at
 * any width, with the crossover at the same 768px breakpoint the rail uses.
 */
export function DesktopOnlyNotice() {
  return (
    <div className="md:hidden h-full min-h-0 flex flex-col items-center justify-center gap-4 px-6 text-center bg-tier-0">
      <TradeDeskMark size={44} />
      <span
        className="uppercase tracking-label-up text-amber"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        Desktop required
      </span>
      <h1 className="text-fg-primary font-medium" style={{ fontSize: 20 }}>
        Open Trade Desk on a larger screen
      </h1>
      <p className="text-tiny text-fg-tertiary max-w-xs leading-relaxed">
        The trading terminal — live chart, option chain, and trade ticket
        side by side — needs the room a laptop or desktop gives it. Come back
        from a wider screen to manage your combines and trade.
      </p>
    </div>
  );
}
