import { z } from "zod";

export const CalendarDaySchema = z.object({
  date: z.string(),
  in_month: z.boolean(),
  realized_pnl: z.number(),
  trade_count: z.number().int(),
  trade_ids: z.array(z.number().int()).default([]),
  is_today: z.boolean().default(false),
});
export type CalendarDay = z.infer<typeof CalendarDaySchema>;

export const CalendarWeekSchema = z.object({
  week_of_month: z.number().int(),
  days: z.array(CalendarDaySchema),
  realized_pnl: z.number(),
  trade_count: z.number().int(),
});
export type CalendarWeek = z.infer<typeof CalendarWeekSchema>;

export const CalendarMonthSchema = z.object({
  month: z.string(),       // "YYYY-MM"
  label: z.string(),       // "May 2026"
  weeks: z.array(CalendarWeekSchema),
  realized_pnl: z.number(),
  trade_count: z.number().int(),
});
export type CalendarMonth = z.infer<typeof CalendarMonthSchema>;
