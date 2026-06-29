import { useMutation } from "@tanstack/react-query";

import { runMonteCarlo } from "@/lib/api";
import type { MonteCarloInput, MonteCarloResult } from "@/types/zerodte";

/**
 * WS5 — Monte-Carlo scenario simulation. A mutation (not a query) because
 * the panel runs it on demand against the current selection / open position
 * with user-tunable inputs (vol, horizon, drift, paths). The result is the
 * terminal-value distribution + P(profit) for the panel to render.
 */
export function useMonteCarlo() {
  return useMutation<MonteCarloResult, Error, MonteCarloInput>({
    mutationFn: (input: MonteCarloInput) => runMonteCarlo(input),
  });
}
