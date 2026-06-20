import { useToastStore, type ToastVariant } from "@/stores/toast";

// Left accent border colour per variant — matches the terminal palette
// (bullish/bearish/warning/cyan). Applied alongside the base hairline border.
const BORDER: Record<ToastVariant, string> = {
  success: "border-l-bullish",
  error: "border-l-bearish",
  warning: "border-l-warning",
  info: "border-l-cyan",
};

const LABEL_COLOR: Record<ToastVariant, string> = {
  success: "text-bullish",
  error: "text-bearish",
  warning: "text-warning",
  info: "text-cyan",
};

const LABEL: Record<ToastVariant, string> = {
  success: "OK",
  error: "Error",
  warning: "Notice",
  info: "Info",
};

/**
 * Global toast stack. Mounted once at the app root (above modals at z-50).
 * Reads the zustand store directly; dispatch from anywhere via the `toast.*`
 * imperative API. aria-live=polite so screen readers announce without
 * stealing focus.
 */
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const remove = useToastStore((s) => s.remove);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed top-3 right-3 z-[60] flex w-[320px] max-w-[calc(100vw-1.5rem)] flex-col gap-2"
      role="region"
      aria-live="polite"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`animate-toast-enter rounded-btn border border-hairline-strong border-l-2 bg-tier-1 shadow-lg ${BORDER[t.variant]}`}
        >
          <div className="flex items-start gap-2 px-3 py-2">
            <span
              className={`pt-0.5 text-tiny uppercase tracking-label-up ${LABEL_COLOR[t.variant]}`}
            >
              {LABEL[t.variant]}
            </span>
            <p className="flex-1 break-words text-sm text-fg-primary">{t.message}</p>
            <button
              type="button"
              onClick={() => remove(t.id)}
              aria-label="Dismiss notification"
              className="text-medium leading-none text-fg-tertiary hover:text-fg-primary"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
