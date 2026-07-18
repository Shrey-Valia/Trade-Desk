import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  AuthCard,
  AuthError,
  AuthInput,
  AuthSubmit,
} from "@/components/auth/AuthCard";
import { useSignup } from "@/hooks/useAuth";
import { acceptDocuments } from "@/lib/legalApi";
import { toast } from "@/stores/toast";

export function SignUpPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Fresh accounts own zero combines — land them on the purchase flow
  // unless the funnel asked for somewhere specific.
  const next = params.get("next") || "/combines/new";
  const signup = useSignup();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agreed, setAgreed] = useState(false);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!agreed) return; // button is disabled; belt-and-suspenders
    signup.mutate(
      {
        email,
        password,
        display_name: displayName.trim() || undefined,
      },
      {
        onSuccess: () => {
          // Record the checked consent server-side (versioned acceptance
          // rows — the purchase gate depends on tos+risk being current).
          // Fire-and-forget: a failure here must not strand the fresh
          // account on the signup page — the purchase-time consent gate
          // re-prompts if this write never landed.
          acceptDocuments(["tos", "risk", "privacy"]).catch(() =>
            toast.error(
              "Couldn't record your agreement — you may be asked to accept again at checkout.",
            ),
          );
          navigate(next, { replace: true });
        },
      },
    );
  };

  return (
    <AuthCard
      title="Create your account"
      subtitle="Then pick a combine and start the evaluation."
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <AuthInput
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          autoFocus
        />
        <AuthInput
          label="Password (8+ characters)"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
        />
        <AuthInput
          label="Display name (optional)"
          type="text"
          value={displayName}
          onChange={setDisplayName}
          autoComplete="nickname"
        />
        <label className="flex items-start gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-amber"
            aria-required
          />
          <span className="text-tiny text-fg-tertiary-2 leading-4">
            I agree to the{" "}
            <Link
              to="/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber hover:underline"
            >
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link
              to="/risk-disclosure"
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber hover:underline"
            >
              Risk Disclosure
            </Link>
          </span>
        </label>
        <AuthError
          message={signup.isError ? (signup.error as Error).message : null}
        />
        <AuthSubmit
          label="Create account"
          pending={signup.isPending}
          disabled={!agreed}
        />
      </form>
      <div className="text-tiny text-fg-tertiary-2 text-center">
        Already trading here?{" "}
        <Link to="/signin" className="text-amber hover:underline">
          Sign in
        </Link>
      </div>
    </AuthCard>
  );
}
