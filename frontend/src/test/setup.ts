// Global test setup: registers jest-dom matchers (toBeInTheDocument,
// toBeDisabled, …) and resets shared module state between tests so the
// zustand singletons (tradeTicket, toast) don't leak across files.
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
