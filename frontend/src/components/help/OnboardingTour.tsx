import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { Modal } from "@/components/ui/Modal";
import { useOnboarding } from "@/stores/onboarding";

interface Step {
  title: string;
  body: string;
}

/** First-run walkthrough of the terminal. Plain modal steps (not anchored
 *  coachmarks); auto-fired only on /positions, where the UI it describes
 *  is actually on screen. */
const STEPS: Step[] = [
  {
    title: "Welcome to Trade Desk",
    body: "A simulated prop-firm terminal. You trade a paid combine to prove consistency, then unlock payouts. No real money moves — but the prices, risk limits, and P&L are real. Here's the 30-second tour.",
  },
  {
    title: "The header pills",
    body: "BAL is your live balance. MLL is the hard floor you must never breach (it fails the combine). DLL is your daily loss budget. RP&L / UP&L split realized vs. open P&L. Watch MLL — it's the one that ends your run.",
  },
  {
    title: "The option chain",
    body: "Pick a strike from the chain on the right to load it into the trade ticket. Right-click (or long-press) a BUY/SELL cell for a one-click quick order. Only 0DTE strikes are tradeable in the terminal.",
  },
  {
    title: "The trade ticket",
    body: "Set your size, order type, and optional trailing stop, then hit BUY or SELL — the direction is which button you press. The risk preview shows your max loss, breakevens, and R-multiple before you fire.",
  },
  {
    title: "Alerts & shortcuts",
    body: "Set price alerts from the bell, and learn the hotkeys: B/S pre-arm buy/sell, C closes the active position, ⌘K opens the command palette, and ? opens help anytime. You're set — good trading.",
  },
];

/** Per-surface seen flag for the buy-screen intro. Kept in localStorage
 *  under the td:onboarding convention (the store's persisted `tourSeen`
 *  covers the terminal walkthrough surface). */
const COMBINE_INTRO_SEEN_KEY = "td:onboarding:combineIntroSeen";

function combineIntroSeen(): boolean {
  try {
    return window.localStorage.getItem(COMBINE_INTRO_SEEN_KEY) != null;
  } catch {
    return true; // storage unavailable — never nag
  }
}

function markCombineIntroSeen(): void {
  try {
    window.localStorage.setItem(COMBINE_INTRO_SEEN_KEY, "1");
  } catch {
    /* storage unavailable */
  }
}

/**
 * First-run onboarding (WS6), gated per surface so each intro fires where
 * its subject is on screen:
 *
 *   /combines/new  a one-card "buy your combine" intro — the post-signup
 *                  landing spot, where the tour used to describe a terminal
 *                  that wasn't visible.
 *   /positions     the full terminal walkthrough, on first visit.
 *
 * Each surface keeps its own seen flag; "Replay tour" in Help still opens
 * the terminal walkthrough from any route.
 */
export function OnboardingTour() {
  const location = useLocation();
  const tourSeen = useOnboarding((s) => s.tourSeen);
  const tourOpen = useOnboarding((s) => s.tourOpen);
  const openTour = useOnboarding((s) => s.openTour);
  const closeTour = useOnboarding((s) => s.closeTour);
  const markTourSeen = useOnboarding((s) => s.markTourSeen);
  const [step, setStep] = useState(0);
  const [introOpen, setIntroOpen] = useState(false);

  const onPositions = location.pathname.startsWith("/positions");
  const onNewCombine = location.pathname.startsWith("/combines/new");

  // Auto-launch the terminal walkthrough on the first /positions visit.
  // Deferred a tick so the shell paints first and the tour doesn't flash
  // before the layout settles.
  useEffect(() => {
    if (!onPositions || tourSeen || tourOpen) return;
    const id = window.setTimeout(() => openTour(), 400);
    return () => window.clearTimeout(id);
  }, [onPositions, tourSeen, tourOpen, openTour]);

  // Auto-launch the buy-screen intro on the first /combines/new visit.
  useEffect(() => {
    if (!onNewCombine || tourOpen || combineIntroSeen()) return;
    const id = window.setTimeout(() => setIntroOpen(true), 400);
    return () => window.clearTimeout(id);
  }, [onNewCombine, tourOpen]);

  // Always start at step 0 on (re)open.
  useEffect(() => {
    if (tourOpen) setStep(0);
  }, [tourOpen]);

  const finish = () => {
    markTourSeen();
    closeTour();
  };

  const closeIntro = () => {
    markCombineIntroSeen();
    setIntroOpen(false);
  };

  if (tourOpen) {
    const isLast = step >= STEPS.length - 1;
    const current = STEPS[step];

    return (
      <Modal
        open={tourOpen}
        onClose={finish}
        labelledBy="onboarding-tour-title"
        panelClassName="w-full max-w-md bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl"
      >
        <div className="flex flex-col gap-3 px-5 py-4">
          <div className="flex items-center justify-between">
            <span className="text-tiny uppercase tracking-label-up text-amber">
              Step {step + 1} of {STEPS.length}
            </span>
            <button
              type="button"
              onClick={finish}
              className="text-tiny text-fg-tertiary-2 hover:text-fg-primary"
            >
              Skip tour
            </button>
          </div>
          <h2
            id="onboarding-tour-title"
            className="text-large font-medium text-fg-primary"
          >
            {current.title}
          </h2>
          <p className="text-sm text-fg-secondary leading-relaxed">{current.body}</p>

          {/* Step dots */}
          <div className="flex items-center gap-1.5 pt-1" aria-hidden>
            {STEPS.map((_, i) => (
              <span
                key={i}
                className={`h-1.5 rounded-full transition-all ${
                  i === step ? "w-5 bg-amber" : "w-1.5 bg-tier-3"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="text-sm text-fg-secondary hover:text-fg-primary disabled:text-fg-disabled disabled:cursor-not-allowed"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => (isLast ? finish() : setStep((s) => s + 1))}
              className="bg-action-buy hover:bg-action-buy-hover text-white rounded-btn px-4 py-1.5 text-sm font-medium"
            >
              {isLast ? "Start trading" : "Next"}
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  if (introOpen && onNewCombine) {
    return (
      <Modal
        open
        onClose={closeIntro}
        labelledBy="combine-intro-title"
        panelClassName="w-full max-w-md bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl"
      >
        <div className="flex flex-col gap-3 px-5 py-4">
          <h2
            id="combine-intro-title"
            className="text-large font-medium text-fg-primary"
          >
            Buy your combine — the rules are the product
          </h2>
          <p className="text-sm text-fg-secondary leading-relaxed">
            Pick an account size to start a paid evaluation. Every size runs
            the same rules engine: a trailing max loss limit you must never
            breach, a daily loss budget, and a profit target that funds the
            account when you hit it with consistency. The checkout is
            simulated — no card is charged.
          </p>
          <p className="text-sm text-fg-tertiary leading-relaxed">
            The full terminal walkthrough plays the first time you open the
            chart.
          </p>
          <div className="flex items-center justify-end pt-2">
            <button
              type="button"
              onClick={closeIntro}
              className="bg-action-buy hover:bg-action-buy-hover text-white rounded-btn px-4 py-1.5 text-sm font-medium"
            >
              Choose my account
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return null;
}
