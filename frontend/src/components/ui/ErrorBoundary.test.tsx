import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ErrorBoundary } from "./ErrorBoundary";

afterEach(cleanup);

/** A child that throws on first render, then renders fine once a flag flips —
 *  lets us prove the boundary's reset() gives a real recovery path. */
function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("kaboom");
  return <div>recovered child</div>;
}

describe("ErrorBoundary", () => {
  it("renders the fallback when a child throws during render", () => {
    // Silence React's expected error logging for the thrown render.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom shouldThrow />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/something went wrong/i)).toBeTruthy();
    // The thrown message is surfaced for debugging.
    expect(screen.getByText(/kaboom/)).toBeTruthy();

    spy.mockRestore();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <ErrorBoundary>
        <div>healthy</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("recovers via the custom fallback's reset()", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    // State-driven so flipping the flag actually re-renders the child with the
    // new prop before reset() re-mounts it.
    function Harness() {
      const [shouldThrow, setShouldThrow] = useState(true);
      return (
        <ErrorBoundary
          fallback={(error, reset) => (
            <button
              type="button"
              onClick={() => {
                setShouldThrow(false);
                reset();
              }}
            >
              retry: {error.message}
            </button>
          )}
        >
          <Boom shouldThrow={shouldThrow} />
        </ErrorBoundary>
      );
    }

    render(<Harness />);
    const retry = screen.getByText(/retry: kaboom/);
    expect(retry).toBeTruthy();
    // Clicking reset clears the captured error; the child re-mounts and (now
    // that the flag flipped) renders successfully.
    fireEvent.click(retry);
    expect(screen.getByText("recovered child")).toBeTruthy();

    spy.mockRestore();
  });
});
