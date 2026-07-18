import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";

/**
 * Shared chrome for the standalone auth pages (no rail shell):
 * centered hairline card on the tier-0 backdrop, wordmark on top.
 */
export function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-tier-0 flex flex-col items-center justify-center px-4">
      <div className="mb-6">
        <TradeDeskLogo />
      </div>
      <div
        className="w-full bg-tier-1 border border-hairline-strong px-6 py-6 flex flex-col gap-4"
        style={{ maxWidth: 380, borderRadius: 4 }}
      >
        <div>
          <div className="text-medium font-medium text-fg-primary">{title}</div>
          {subtitle && (
            <div className="text-tiny text-fg-tertiary mt-1">{subtitle}</div>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

export function AuthInput({
  label,
  type,
  value,
  onChange,
  autoComplete,
  autoFocus,
}: {
  label: string;
  type: "email" | "password" | "text";
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  autoFocus?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        spellCheck={false}
        className="h-9 px-2.5 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary focus:border-amber focus:outline-none"
        style={{ fontSize: 13 }}
      />
    </label>
  );
}

export function AuthSubmit({
  label,
  pending,
  disabled = false,
}: {
  label: string;
  pending: boolean;
  /** Extra gate beyond pending (e.g. signup's required consent checkbox). */
  disabled?: boolean;
}) {
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      className="h-9 w-full uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 disabled:opacity-50 disabled:cursor-not-allowed rounded-btn font-medium"
      style={{ fontSize: 12 }}
    >
      {pending ? "Working…" : label}
    </button>
  );
}

export function AuthError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="text-tiny text-bearish" role="alert">
      {message}
    </div>
  );
}
