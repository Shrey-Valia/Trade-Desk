import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchMe, signin, signout, signup } from "@/lib/api";
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
      qc.setQueryData(ME_KEY, user);
      // A different user may have signed in — every cached per-user
      // payload (trades, account state, stars) is suspect.
      qc.invalidateQueries();
      toast.success(`Signed in as ${user.email}.`);
    },
  });
}

export function useSignout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => signout(),
    onSuccess: () => {
      // Drop everything — all user data is stale after signout.
      qc.clear();
    },
  });
}
