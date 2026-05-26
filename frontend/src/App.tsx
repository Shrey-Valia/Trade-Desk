import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { RailShell } from "@/components/layout/RailShell";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { JournalPage } from "@/pages/JournalPage";
import { PositionsPage } from "@/pages/PositionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { WatchlistPage } from "@/pages/WatchlistPage";
// ZeroDtePage retired from navigation; 0DTE entry now lives on the CHART
// view via the toolbar's "0DTE STRADDLE" button. Page kept on disk for
// rollback during the transition; not imported here.

/**
 * Top-level routing.
 *
 * Only the rail-shell destinations are reachable. The retired
 * Analysis-mode pages (DashboardPage / MarketPage / NewsPage /
 * SignalPage) and their shell chrome (TopNavBar / DashboardHeader /
 * TickerTape) remain on disk so we can cannibalize pieces of the
 * signal verdict card / regime card / etc. in a future step — but
 * nothing routes to them. The legacy paths `/`, `/market`, `/news`,
 * `/signal` and any unknown URL all funnel into `/positions`, the
 * unambiguous product home.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<RailShell />}>
          <Route path="/positions" element={<PositionsPage />} />
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        {/* Everything else — including the retired Analysis paths and
            unknown URLs — bounces to the new chart-first home. */}
        <Route path="*" element={<Navigate to="/positions" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
