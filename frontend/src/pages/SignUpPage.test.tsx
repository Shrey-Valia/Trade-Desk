import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeQueryWrapper } from "@/test/queryWrapper";

// ── Mocks ────────────────────────────────────────────────────────────────────
// The signup mutation and the policy fetch are both mocked at the module
// boundary; the component's own gating logic (field shown? submit enabled?
// code forwarded?) is what's under test.

const signupMutate = vi.fn();
const signupState = { isError: false, error: null as Error | null };
vi.mock("@/hooks/useAuth", () => ({
  useSignup: () => ({
    mutate: signupMutate,
    isPending: false,
    isError: signupState.isError,
    error: signupState.error,
  }),
}));

const fetchSignupPolicyMock = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchSignupPolicy: () => fetchSignupPolicyMock(),
}));

vi.mock("@/lib/legalApi", async (importOriginal) => ({
  // Keep the REAL errorMessage — stripping the "<code>: " prefix off a gate
  // refusal is behavior this page owns and the test below asserts on.
  ...(await importOriginal<typeof import("@/lib/legalApi")>()),
  acceptDocuments: () => Promise.resolve(),
}));

import { SignUpPage } from "@/pages/SignUpPage";

function renderPage(initialEntry = "/signup") {
  const { wrapper: Wrapper } = makeQueryWrapper();
  return render(
    <Wrapper>
      <MemoryRouter initialEntries={[initialEntry]}>
        <SignUpPage />
      </MemoryRouter>
    </Wrapper>,
  );
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/^email$/i), "new@test.local");
  await user.type(screen.getByLabelText(/^password/i), "password123");
  await user.click(screen.getByRole("checkbox"));
}

describe("SignUpPage invite gate", () => {
  beforeEach(() => {
    signupMutate.mockClear();
    fetchSignupPolicyMock.mockReset();
    signupState.isError = false;
    signupState.error = null;
  });

  it("hides the invite field on an open deployment", async () => {
    fetchSignupPolicyMock.mockResolvedValue({ require_invite: false });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(fetchSignupPolicyMock).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByLabelText(/invite code/i)).toBeNull();

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(signupMutate).toHaveBeenCalledTimes(1);
    // No code typed → the field is omitted rather than sent as "".
    expect(signupMutate.mock.calls[0][0].invite_code).toBeUndefined();
  });

  it("requires a code — and forwards it — when the deployment is invite-only", async () => {
    fetchSignupPolicyMock.mockResolvedValue({ require_invite: true });
    const user = userEvent.setup();
    renderPage();

    const field = await screen.findByLabelText(/invite code/i);
    await fillRequiredFields(user);

    // Consent checked but no code: submit stays disabled.
    const submit = screen.getByRole("button", { name: /create account/i });
    expect(submit).toBeDisabled();

    await user.type(field, "td-7k4m-qx92");
    // Typed lowercase, upper-cased in place — codes are canonical uppercase.
    expect(field).toHaveValue("TD-7K4M-QX92");
    expect(submit).toBeEnabled();

    await user.click(submit);
    expect(signupMutate.mock.calls[0][0].invite_code).toBe("TD-7K4M-QX92");
  });

  it("prefills the code from ?invite= so one link is enough", async () => {
    fetchSignupPolicyMock.mockResolvedValue({ require_invite: true });
    renderPage("/signup?invite=TD-ABCD-2345");

    expect(await screen.findByLabelText(/invite code/i)).toHaveValue(
      "TD-ABCD-2345",
    );
  });

  it("shows a rejected code without leaking the machine-readable prefix", async () => {
    fetchSignupPolicyMock.mockResolvedValue({ require_invite: true });
    signupState.isError = true;
    signupState.error = new Error(
      "invalid_invite: That invite code isn't valid.",
    );
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That invite code isn't valid.");
    expect(alert.textContent).not.toContain("invalid_invite:");
  });

  it("falls back to the open form when the policy fetch fails", async () => {
    // The server enforces the gate regardless; a policy outage must not
    // wedge the page behind a field nobody can satisfy.
    fetchSignupPolicyMock.mockRejectedValue(new Error("offline"));
    renderPage();

    await waitFor(() =>
      expect(fetchSignupPolicyMock).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByLabelText(/invite code/i)).toBeNull();
  });
});
