/**
 * Inline load-failure state for query-backed pages. Distinct from the
 * empty state ("you have nothing") — this means the request itself failed,
 * so the page must NOT fall through to a "no accounts / no payouts" screen
 * that an existing user would read as data loss. Offers a retry.
 */
export function LoadError({
  subject = "this data",
  onRetry,
}: {
  subject?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="px-1 py-10 text-center text-tiny text-bearish">
      Couldn&apos;t load {subject}.{" "}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="underline text-amber hover:opacity-80"
        >
          Retry
        </button>
      )}
    </div>
  );
}
