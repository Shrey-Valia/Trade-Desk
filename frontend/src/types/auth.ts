import { z } from "zod";

export const UserOutSchema = z.object({
  id: z.number().int(),
  email: z.string(),
  display_name: z.string().nullable(),
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
