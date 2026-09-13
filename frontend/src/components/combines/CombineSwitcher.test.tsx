import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CombineOut } from "@/types/combine";

const activateMutate = vi.fn();
const combinesRef = {
  current: {
    combines: [] as CombineOut[],
    active_combine_id: 1 as number | null,
    copy_lead_combine_id: null as number | null,
  },
};

vi.mock("@/hooks/useCombines", () => ({
  useCombines: () => ({ data: combinesRef.current }),
  useActivateCombine: () => ({ mutate: activateMutate, isPending: false }),
}));

import { CombineSwitcher } from "@/components/combines/CombineSwitcher";

function makeCombine(overrides: Partial<CombineOut>): CombineOut {
  return {
    id: 1,
    name: "Main 50K",
    tier: "50K",
    account_code: "ACC-1",
    status: "active",
    outcome: "active",
    balance: 50_000,
    mll: 48_000,
    funded: false,
    copy_follow: false,
    ...overrides,
  } as CombineOut;
}

function renderSwitcher() {
  combinesRef.current = {
    combines: [
      makeCombine({ id: 1, name: "Main 50K" }),
      makeCombine({ id: 2, name: "Backup 25K", tier: "25K", account_code: "ACC-2" }),
    ],
    active_combine_id: 1,
    copy_lead_combine_id: null,
  };
  return render(
    <MemoryRouter>
      <CombineSwitcher />
    </MemoryRouter>,
  );
}

/**
 * The popup used to declare role="listbox" while rendering plain <button>
 * children — a screen reader announced a listbox with zero options — and it
 * had no Escape handler, so a keyboard user who opened it was stuck.
 */
describe("CombineSwitcher popup a11y", () => {
  afterEach(() => vi.clearAllMocks());

  it("does not claim a listbox role with no options", async () => {
    renderSwitcher();
    await userEvent.click(screen.getByRole("button", { name: /Main 50K/ }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    // Every combine plus the "start a new combine" action is a real button.
    expect(screen.getByRole("button", { name: /Backup 25K/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Start a new combine/ }),
    ).toBeInTheDocument();
  });

  it("closes the popup on Escape without switching combines", async () => {
    renderSwitcher();
    await userEvent.click(screen.getByRole("button", { name: /Main 50K/ }));
    expect(screen.getByRole("button", { name: /Backup 25K/ })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("button", { name: /Backup 25K/ })).not.toBeInTheDocument();
    expect(activateMutate).not.toHaveBeenCalled();
  });
});
