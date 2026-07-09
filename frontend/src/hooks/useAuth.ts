import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  changePassword,
  fetchMe,
  signin,
  signout,
  signup,
  type ChangePasswordInput,
} from "@/lib/api";
import { resetSessionStores } from "@/lib/session";
import { toast } from "@/stores/toast";
import type { SigninInput, SignupInput } from "@/types/auth";

export const ME_KEY = ["auth", "me"] as const;

/**
 * Session probe. 401 → isError (logged out) — that's a normal state,
 * not a failure, so retries are off and the result is cached until an
 * auth mutation invalidates it.
 */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: fetchMe,
    retry: false,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useSignup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SignupInput) => signup(input),
    onSuccess: (user) => {
      qc.setQueryData(ME_KEY, user);
      toast.success("Account created — welcome.");
    },
  });
}

export function useSignin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SigninInput) => signin(input),
    onSuccess: (user) => {
      // A different user may be signing in. DROP the prior user's cached
      // payloads outright (not just invalidate) so their trades / balances
      // never flash for the new user before a refetch lands, and reset the
      // session-scoped zustand stores (selection / journal scope). Clear first,
      // then seed the new identity.
      qc.clear();
      resetSessionStores();
      qc.setQueryData(ME_KEY, user);
      toast.success(`Signed in as ${user.email}.`);
    },
  });
}

export function useSignout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => signout(),
    onSuccess: () => {
      // Drop everything — all user data is stale after signout. Clear the
      // query cache AND the session-scoped zustand stores (selection / journal
      // scope) so nothing survives into the next user's session in this tab.
      qc.clear();
      resetSessionStores();
    },
  });
}

/** Change password. Success revokes every OTHER session server-side (this
 *  one stays signed in). Errors — 403 wrong current password, 422 policy —
 *  are left on `mutation.error` for the form to render verbatim; no error
 *  toast here so the message sits next to the fields it belongs to. */
export function useChangePassword() {
  return useMutation({
    mutationFn: (input: ChangePasswordInput) => changePassword(input),
    onSuccess: () =>
      toast.success("Password changed — your other sessions were signed out."),
  });
}
