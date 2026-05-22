import { z } from "zod";

export const EventTypeSchema = z.enum([
  "earnings",
  "fomc",
  "fomc_minutes",
  "fed_speak",
  "economic",
  "opex",
  "quad_witching",
]);

export const ImportanceSchema = z.enum(["low", "medium", "high"]);

export const CalendarEventSchema = z.object({
  type: EventTypeSchema,
  title: z.string(),
  ticker: z.string().nullable().optional(),
  time: z.string().nullable().optional(),
  importance: ImportanceSchema,
});

export const CalendarDaySchema = z.object({
  date: z.string(),
  is_today: z.boolean(),
  events: z.array(CalendarEventSchema),
});

export const CalendarResponseSchema = z.object({
  days: z.array(CalendarDaySchema),
  notes: z.record(z.string()).default({}),
});

export type CalendarEvent = z.infer<typeof CalendarEventSchema>;
export type CalendarDay = z.infer<typeof CalendarDaySchema>;
export type CalendarResponse = z.infer<typeof CalendarResponseSchema>;
export type EventType = z.infer<typeof EventTypeSchema>;
