import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeQueryWrapper } from "@/test/queryWrapper";

import { QuickOrder, type QuickOrderTarget } from "./QuickOrder";

const target: QuickOrderTarget = {
  symbol: "SPY",
  side: "call",
  strike: 500,
  price: 1.0, // open-time snapshot
  expiry: "2026-07-25",
  anchor: { x: 100, y: 100 },
};

function renderQuickOrder(livePrice: number | null) {
  const { wrapper: Wrapper } = makeQueryWrapper();
  const utils = render(
    <QuickOrder
      target={target}
      livePrice={livePrice}
      maxContracts={5}
      onClose={() => {}}
      onFired={() => {}}
    />,
    { wrapper: Wrapper },
  );
  const rerender = (lp: number | null) =>
    utils.rerender(
      <QuickOrder
        target={target}
        livePrice={lp}
        maxContracts={5}
        onClose={() => {}}
        onFired={() => {}}
      />,
    );
  return { ...utils, rerender };
}

const triggerInput = () =>
  screen.getByLabelText("Trigger price (option premium)") as HTMLInputElement;

describe("QuickOrder stale-seed handling", () => {
  afterEach(() => vi.clearAllMocks());

  it("seeds the trigger from the live price, not the open-time snapshot", () => {
    renderQuickOrder(1.5); // live has moved past the 1.0 snapshot
    fireEvent.click(screen.getByRole("button", { name: "lmt" }));
    expect(triggerInput().value).toBe("1.5");
  });

  it("re-seeds the unedited trigger as the live price refetches", () => {
    const { rerender } = renderQuickOrder(1.5);
    fireEvent.click(screen.getByRole("button", { name: "lmt" }));
    expect(triggerInput().value).toBe("1.5");
    rerender(1.8); // a 10s chain refetch moved the premium
    expect(triggerInput().value).toBe("1.8");
  });

  it("never clobbers a trigger the user has typed", () => {
    const { rerender } = renderQuickOrder(1.5);
    fireEvent.click(screen.getByRole("button", { name: "lmt" }));
    fireEvent.change(triggerInput(), { target: { value: "2.25" } });
    expect(triggerInput().value).toBe("2.25");
    rerender(1.9); // live moves — the user's chosen limit must stand
    expect(triggerInput().value).toBe("2.25");
  });

  it("falls back to the snapshot when no live price is available", () => {
    renderQuickOrder(null);
    fireEvent.click(screen.getByRole("button", { name: "lmt" }));
    expect(triggerInput().value).toBe("1"); // target.price snapshot
  });
});
