import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * A fresh QueryClient + provider for hook/component tests. Retries are off
 * (so a rejected queryFn surfaces immediately instead of looping) and the
 * gcTime is short so no cache leaks between tests. Returns both the wrapper
 * and the client so a test can pre-seed or inspect the cache.
 */
export function makeQueryWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      // retry off so a rejected queryFn fails fast. gcTime kept non-zero so a
      // query that loses its observer (e.g. after a rerender to a new key)
      // lingers in the cache long enough for tests to inspect both entries.
      queries: { retry: false, gcTime: 5 * 60_000, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
