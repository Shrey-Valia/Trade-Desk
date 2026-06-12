import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  AuthCard,
  AuthError,
  AuthInput,
  AuthSubmit,
} from "@/components/auth/AuthCard";
import { useSignup } from "@/hooks/useAuth";

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

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    signup.mutate(
      {
        email,
        password,
        display_name: displayName.trim() || undefined,
      },
      { onSuccess: () => navigate(next, { replace: true }) },
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
        <AuthError
          message={signup.isError ? (signup.error as Error).message : null}
        />
        <AuthSubmit label="Create account" pending={signup.isPending} />
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
