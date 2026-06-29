import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/Modal";
import { useOnboarding } from "@/stores/onboarding";

interface Step {
  title: string;
  body: string;
}

/** First-run walkthrough of the terminal. Plain modal steps (not anchored
 *  coachmarks) so it works regardless of which route the user lands on. */
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

/**
 * First-run onboarding tour (WS6). Auto-opens once for a fresh browser
 * (gated on the persisted `tourSeen` flag), and can be replayed from Help.
 * A multi-step modal walkthrough built on the accessible Modal primitive.
 */
export function OnboardingTour() {
  const tourSeen = useOnboarding((s) => s.tourSeen);
  const tourOpen = useOnboarding((s) => s.tourOpen);
  const openTour = useOnboarding((s) => s.openTour);
  const closeTour = useOnboarding((s) => s.closeTour);
  const markTourSeen = useOnboarding((s) => s.markTourSeen);
  const [step, setStep] = useState(0);

  // Auto-launch once for a brand-new browser. Deferred a tick so the shell
  // paints first and the tour doesn't flash before the layout settles.
  useEffect(() => {
    if (tourSeen || tourOpen) return;
    const id = window.setTimeout(() => openTour(), 400);
    return () => window.clearTimeout(id);
  }, [tourSeen, tourOpen, openTour]);

  // Always start at step 0 on (re)open.
  useEffect(() => {
    if (tourOpen) setStep(0);
  }, [tourOpen]);

  const finish = () => {
    markTourSeen();
    closeTour();
  };

  if (!tourOpen) return null;

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
