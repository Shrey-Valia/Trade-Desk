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
  /** Required only while the deployment is invite-only — see
   *  SignupPolicySchema / GET /api/auth/signup-policy. */
  invite_code?: string;
}

/** Whether the signup form must collect an invite code. The server-side
 *  gate is the enforcement; this only shapes the form. */
export const SignupPolicySchema = z.object({
  require_invite: z.boolean(),
});
export type SignupPolicy = z.infer<typeof SignupPolicySchema>;

export interface SigninInput {
  email: string;
  password: string;
}
