import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  AuthCard,
  AuthError,
  AuthInput,
  AuthSubmit,
} from "@/components/auth/AuthCard";
import { useSignin } from "@/hooks/useAuth";

export function SignInPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/positions";
  const signin = useSignin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    signin.mutate(
      { email, password },
      { onSuccess: () => navigate(next, { replace: true }) },
    );
  };

  return (
    <AuthCard title="Sign in" subtitle="Welcome back to the desk.">
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
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        <div className="flex justify-end -mt-1">
          <Link
            to="/forgot-password"
            className="text-tiny text-fg-tertiary-2 hover:text-amber"
          >
            Forgot password?
          </Link>
        </div>
        <AuthError
          message={signin.isError ? (signin.error as Error).message : null}
        />
        <AuthSubmit label="Sign in" pending={signin.isPending} />
      </form>
      <div className="text-tiny text-fg-tertiary-2 text-center">
        New here?{" "}
        <Link
          to={`/signup${next !== "/positions" ? `?next=${encodeURIComponent(next)}` : ""}`}
          className="text-amber hover:underline"
        >
          Create an account
        </Link>
      </div>
    </AuthCard>
  );
}
