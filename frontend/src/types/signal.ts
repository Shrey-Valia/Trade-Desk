import { z } from "zod";

export const VerdictTypeSchema = z.enum([
  "sell_premium",
  "buy_premium",
  "directional_long",
  "directional_short",
  "neutral",
  "avoid",
]);
export type VerdictType = z.infer<typeof VerdictTypeSchema>;

export const ConvictionLabelSchema = z.enum(["high", "moderate", "low"]);
export type ConvictionLabel = z.infer<typeof ConvictionLabelSchema>;

export const SignalReasonSchema = z.object({
  label: z.string(),
  detail: z.string(),
  weight: z.number().int(),
});
export type SignalReason = z.infer<typeof SignalReasonSchema>;

export const MockSweepSchema = z.object({
  strike: z.number(),
  expiry: z.string(),
  side: z.enum(["call", "put"]),
  premium: z.number(),
  contracts: z.number().int(),
  aggressor: z.enum(["bid", "ask"]),
  timestamp: z.string(),
  is_mock: z.boolean(),
});
export type MockSweep = z.infer<typeof MockSweepSchema>;

export const SignalVerdictSchema = z.object({
  symbol: z.string(),
  verdict: z.string(),
  verdict_type: VerdictTypeSchema,
  conviction: z.number().int().min(0).max(100),
  conviction_label: ConvictionLabelSchema,
  signals_agreeing: z.array(SignalReasonSchema),
  signals_conflicting: z.array(SignalReasonSchema),
  thesis: z.string(),
  suggested_structure: z.string().nullable(),
  suggested_structure_detail: z.string().nullable(),
  mock_flow_used: z.boolean(),
  mock_sweeps: z.array(MockSweepSchema),
});
export type SignalVerdict = z.infer<typeof SignalVerdictSchema>;
