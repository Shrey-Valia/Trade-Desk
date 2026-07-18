import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";

import {
  AuthCard,
  AuthError,
  AuthInput,
  AuthSubmit,
} from "@/components/auth/AuthCard";
import { forgotPassword } from "@/lib/legalApi";

/**
 * /forgot-password — start account recovery. The backend answers 204 for
 * known AND unknown emails (no account enumeration), so success always
 * shows the same neutral confirmation. The only real error here is the
 * rate limiter (429) or a malformed email (422).
 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const request = useMutation({
    mutationFn: (address: string) => forgotPassword(address),
    onSuccess: () => setSent(true),
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim()) request.mutate(email.trim());
  };

  return (
    <AuthCard
      title="Reset your password"
      subtitle="We'll email you a single-use reset link."
    >
      {sent ? (
        <div className="flex flex-col gap-4">
          <div
            className="border border-hairline-strong bg-tier-2 px-3 py-3 text-tiny text-fg-secondary leading-5"
            style={{ borderRadius: 4 }}
            role="status"
          >
            If an account exists, a reset link is on its way. Check your
            inbox — the link expires after a couple of hours and works once.
          </div>
          <div className="text-tiny text-fg-tertiary-2 text-center">
            Didn't get it?{" "}
            <button
              type="button"
              onClick={() => setSent(false)}
              className="text-amber hover:underline"
            >
              Send again
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <AuthInput
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            autoFocus
          />
          <AuthError
            message={request.isError ? (request.error as Error).message : null}
          />
          <AuthSubmit
            label="Email reset link"
            pending={request.isPending}
            disabled={!email.trim()}
          />
        </form>
      )}
      <div className="text-tiny text-fg-tertiary-2 text-center">
        Remembered it?{" "}
        <Link to="/signin" className="text-amber hover:underline">
          Sign in
        </Link>
      </div>
    </AuthCard>
  );
}
