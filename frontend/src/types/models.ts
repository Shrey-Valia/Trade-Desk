import { z } from "zod";

export const CatboostErMoveSchema = z.object({
  value: z.number(),
  implied_compare: z.number().nullable(),
  interpretation: z.string(),
  n_training_events: z.number(),
  baseline_beaten: z.boolean(),
});

export const LstmVolForecastSchema = z.object({
  predicted_rv_7d: z.number(),
  current_iv30: z.number().nullable(),
  vrp_implied: z.number().nullable(),
  interpretation: z.string(),
  baseline_beaten: z.boolean(),
  n_training_windows: z.number(),
});

export const RegimeSignalSchema = z.object({
  name: z.string(),
  value: z.number(),
  rule: z.string(),
  satisfied: z.boolean(),
});

export const RfRegimeSchema = z.object({
  regime: z.string(),
  label: z.string(),
  confidence: z.number(),
  contributing_signals: z.array(RegimeSignalSchema),
});

export const MlpTrendSchema = z.object({
  prob_up: z.number(),
  interpretation: z.string(),
  baseline_beaten: z.boolean(),
  n_training_windows: z.number(),
});

export const EnsembleComponentsSchema = z.object({
  lstm_contribution: z.number().nullable(),
  catboost_contribution: z.number().nullable(),
  mlp_contribution: z.number().nullable(),
  regime_contribution: z.number().nullable(),
});

export const EnsembleEdgeSchema = z.object({
  z_score: z.number(),
  raw_predicted_return: z.number(),
  interpretation: z.string(),
  baseline_beaten: z.boolean(),
  components: EnsembleComponentsSchema,
  mlp_in_production: z.boolean(),
});

export const VolEdgeSchema = z.object({
  verdict: z.string(),
  label: z.string(),
  rationale: z.string(),
  signals_used: z.array(z.string()),
});

export const ModelSignalsResponseSchema = z.object({
  lstm_vol_forecast: LstmVolForecastSchema.nullable(),
  catboost_er_move: CatboostErMoveSchema.nullable(),
  rf_regime: RfRegimeSchema.nullable(),
  // Phase 7.9: MLP + Ensemble cards consolidated out of the UI.
  // Fields preserved in schema for API-shape compatibility; always null.
  mlp_trend: MlpTrendSchema.nullable(),
  ensemble_edge: EnsembleEdgeSchema.nullable(),
  vol_edge: VolEdgeSchema.nullable(),
  updated_at: z.string(),
});

export type CatboostErMove = z.infer<typeof CatboostErMoveSchema>;
export type LstmVolForecast = z.infer<typeof LstmVolForecastSchema>;
export type RfRegime = z.infer<typeof RfRegimeSchema>;
export type RegimeSignal = z.infer<typeof RegimeSignalSchema>;
export type MlpTrend = z.infer<typeof MlpTrendSchema>;
export type EnsembleEdge = z.infer<typeof EnsembleEdgeSchema>;
export type EnsembleComponents = z.infer<typeof EnsembleComponentsSchema>;
export type VolEdge = z.infer<typeof VolEdgeSchema>;
export type ModelSignalsResponse = z.infer<typeof ModelSignalsResponseSchema>;
