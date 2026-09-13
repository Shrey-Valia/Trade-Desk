import { render, screen } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { describe, expect, it } from "vitest";

import { MetricPill } from "@/components/ui/MetricPill";

expect.extend(toHaveNoViolations);

/**
 * The `hint` (the BAL/MLL/DLL/CLOSED-P&L explanation) used to ship only as a
 * `title` on a non-focusable <div> — mouse-hover only, despite the dotted
 * underline advertising it. It's now reachable by Tab and announced.
 */
describe("MetricPill hint accessibility", () => {
  it("is focusable and announces label + value + hint when a hint is set", () => {
    render(
      <MetricPill
        label="MLL"
        value="$47,000"
        sub="floor"
        hint="Max loss limit — the account fails if balance closes below it."
      />,
    );
    const pill = screen.getByRole("group", {
      name: "MLL $47,000 floor — Max loss limit — the account fails if balance closes below it.",
    });
    expect(pill).toHaveAttribute("tabindex", "0");
  });

  it("stays a plain non-focusable box with no hint", () => {
    const { container } = render(<MetricPill label="UP&L" value="$120" />);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(container.firstElementChild).not.toHaveAttribute("tabindex");
  });

  it("skips non-primitive nodes rather than stringifying them", () => {
    render(
      <MetricPill label={<em>BAL</em>} value="$50,000" hint="Account balance." />,
    );
    expect(
      screen.getByRole("group", { name: "$50,000 — Account balance." }),
    ).toBeInTheDocument();
  });

  it("has no axe violations with a hint", async () => {
    const { container } = render(
      <MetricPill label="DLL" value="$1,000" hint="Daily loss limit." />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
