import { render } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { describe, expect, it } from "vitest";

expect.extend(toHaveNoViolations);

import { HelpOverlay } from "@/components/help/HelpOverlay";
import { OnboardingTour } from "@/components/help/OnboardingTour";
import { Modal } from "@/components/ui/Modal";
import { useOnboarding } from "@/stores/onboarding";

/**
 * axe-core accessibility pass over the WS6 overlays (jsdom harness).
 *
 * These are the net-new interactive surfaces WS6 adds; the run asserts zero
 * axe violations (labels present, dialog roles wired, headings nested). It
 * runs in the existing vitest/jsdom pipeline — no browser needed — so the
 * a11y gate stays in CI with every other test.
 */
describe("a11y — WS6 overlays (axe-core)", () => {
  it("HelpOverlay has no axe violations", async () => {
    useOnboarding.setState({ helpOpen: true });
    const { container } = render(<HelpOverlay />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("OnboardingTour has no axe violations", async () => {
    useOnboarding.setState({ tourOpen: true, tourSeen: false });
    const { container } = render(<OnboardingTour />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("Modal primitive (labelled dialog) has no axe violations", async () => {
    const { container } = render(
      <Modal open onClose={() => {}} labelledBy="t" panelClassName="bg-tier-1">
        <h2 id="t">Dialog title</h2>
        <button type="button">OK</button>
      </Modal>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
