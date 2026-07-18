import { z } from "zod";

export const UserOutSchema = z.object({
  id: z.number().int(),
  email: z.string(),
  display_name: z.string().nullable(),
  // "trader" | "admin" — gates the /admin console. Defaulted so a cached
  // pre-upgrade response still parses.
  role: z.string().default("trader"),
});
export type UserOut = z.infer<typeof UserOutSchema>;

export interface SignupInput {
  email: string;
  password: string;
  display_name?: string;
}

export interface SigninInput {
  email: string;
  password: string;
}
