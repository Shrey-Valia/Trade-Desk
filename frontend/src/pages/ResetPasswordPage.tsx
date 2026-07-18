import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";

import {
  AuthCard,
  AuthError,
  AuthInput,
  AuthSubmit,
} from "@/components/auth/AuthCard";
import { errorMessage, resetPassword } from "@/lib/legalApi";
import { toast } from "@/stores/toast";

/**
 * /reset-password?token=… — complete account recovery from the emailed
 * link. Success revokes every session server-side, so the user is sent to
 * /signin to authenticate with the new password. A 400 ("invalid_token: …"
 * — expired, used, or malformed) renders a clear error with a path back to
 * requesting a fresh link.
 */
export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const reset = useMutation({
    mutationFn: () => resetPassword(token, password),
    onSuccess: () => {
      toast.success("Password updated — sign in with your new password.");
      navigate("/signin", { replace: true });
    },
  });

  // The emailed link carries ?token=…; without it there is nothing to
  // submit — steer straight to requesting a fresh link.
  if (!token) {
    return (
      <AuthCard title="Reset your password">
        <div
          className="border border-bearish bg-tier-2 px-3 py-3 text-tiny text-bearish leading-5"
          style={{ borderRadius: 4 }}
          role="alert"
        >
          This reset link is missing its token. Open the link from the email
          exactly as sent, or request a new one.
        </div>
        <Link
          to="/forgot-password"
          className="text-tiny text-amber hover:underline text-center"
        >
          Request a new reset link
        </Link>
      </AuthCard>
    );
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setLocalError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setLocalError("Passwords don't match.");
      return;
    }
    setLocalError(null);
    reset.mutate();
  };

  const tokenRejected = reset.isError;

  return (
    <AuthCard
      title="Choose a new password"
      subtitle="This signs out every other session on your account."
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <AuthInput
          label="New password (8+ characters)"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          autoFocus
        />
        <AuthInput
          label="Confirm new password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
        />
        <AuthError
          message={
            localError ?? (tokenRejected ? errorMessage(reset.error) : null)
          }
        />
        {tokenRejected && (
          <div className="text-tiny text-fg-tertiary-2">
            Links expire after a couple of hours and work once.{" "}
            <Link to="/forgot-password" className="text-amber hover:underline">
              Request a new reset link
            </Link>
          </div>
        )}
        <AuthSubmit
          label="Set new password"
          pending={reset.isPending}
          disabled={!password || !confirm}
        />
      </form>
      <div className="text-tiny text-fg-tertiary-2 text-center">
        <Link to="/signin" className="text-amber hover:underline">
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  );
}
