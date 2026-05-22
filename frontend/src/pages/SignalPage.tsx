import { SignalView } from "@/components/signal/SignalView";
import { WatchlistColumn } from "@/components/watchlist/WatchlistColumn";

/**
 * /signal route — reuses the watchlist rail so the user can switch
 * tickers without bouncing back to /dashboard. Layout mirrors the
 * dashboard's 240px + flex-1 split for muscle-memory consistency.
 */
export function SignalPage() {
  return (
    <div className="flex flex-1 min-h-0">
      <WatchlistColumn />
      <SignalView />
    </div>
  );
}
