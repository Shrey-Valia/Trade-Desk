import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Optional custom fallback. Receives the error and a reset() that clears
   *  the boundary so the subtree re-mounts and re-renders from scratch. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * App-shell error boundary — a render crash anywhere inside the tree shows a
 * recoverable error panel instead of a blank white page. React only catches
 * render/lifecycle errors via class components, so this stays a class.
 *
 * `reset()` clears the captured error; React then re-mounts the children, so
 * "Try again" gives the user a real recovery path (e.g. after a transient
 * data shape blew up a render). Errors are also forwarded to Sentry when the
 * SDK is present on `window` (no-op otherwise) and always logged to console.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always surface in the console for local debugging.
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught a render error", error, info);
    // Forward to Sentry if the browser SDK happens to be loaded. Guarded so
    // there's zero hard dependency and no crash when it isn't.
    const sentry = (window as unknown as {
      Sentry?: { captureException?: (e: unknown) => void };
    }).Sentry;
    sentry?.captureException?.(error);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error) {
      if (this.props.fallback) return this.props.fallback(error, this.reset);
      return <DefaultFallback error={error} onReset={this.reset} />;
    }
    return this.props.children;
  }
}

function DefaultFallback({
  error,
  onReset,
}: {
  error: Error;
  onReset: () => void;
}) {
  return (
    <div
      role="alert"
      className="min-h-screen flex items-center justify-center bg-tier-0 p-6"
    >
      <div className="max-w-md w-full border border-hairline bg-tier-1 p-6 text-center flex flex-col items-center gap-3">
        <span className="text-bearish uppercase tracking-label-up text-tiny">
          Something went wrong
        </span>
        <p className="text-fg-secondary text-tiny">
          A part of the app hit an unexpected error and stopped rendering. Your
          data is safe — try again, or reload the page.
        </p>
        {error.message && (
          <code className="text-fg-tertiary text-tiny break-words max-w-full">
            {error.message}
          </code>
        )}
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={onReset}
            className="h-7 px-3 uppercase tracking-label-up text-tiny border border-amber text-amber hover:bg-tier-2"
            style={{ borderRadius: 0 }}
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="h-7 px-3 uppercase tracking-label-up text-tiny border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
            style={{ borderRadius: 0 }}
          >
            Reload
          </button>
        </div>
      </div>
    </div>
  );
}
