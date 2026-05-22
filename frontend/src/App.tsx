import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { DashboardHeader } from "@/components/layout/DashboardHeader";
import { RailShell } from "@/components/layout/RailShell";
import { TopNavBar } from "@/components/layout/TopNavBar";
import { TickerTape } from "@/components/tradingview/TickerTape";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { JournalPage } from "@/pages/JournalPage";
import { MarketPage } from "@/pages/MarketPage";
import { NewsPage } from "@/pages/NewsPage";
import { PositionsPage } from "@/pages/PositionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SignalPage } from "@/pages/SignalPage";
import { WatchlistPage } from "@/pages/WatchlistPage";

const COLD_OPEN_FLAG = "td:cold-open-routed";

/**
 * Top-level routing.
 *
 *   • RailShell wraps every chart-first destination (Chart / Journal /
 *     Analytics / Watchlist / Settings) so the left rail is present on
 *     all of them and only on them.
 *
 *   • The retired ANALYSIS shell (Dashboard / Market / News / Signal)
 *     remains routable so direct URLs still work, but nothing in the
 *     rail-shell UI links into it. The intent is to retire it as a
 *     navigation destination without deleting the code, so later steps
 *     can pull pieces (signal verdict card, regime card, etc.) into
 *     the new structure if useful.
 */
export default function App() {
  return (
    <BrowserRouter>
      <ColdOpenRedirect />
      <Routes>
        <Route element={<RailShell />}>
          <Route path="/positions" element={<PositionsPage />} />
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="/*" element={<AnalysisShell />} />
      </Routes>
    </BrowserRouter>
  );
}

function ColdOpenRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (location.pathname !== "/") return;
    if (window.localStorage.getItem(COLD_OPEN_FLAG)) return;
    window.localStorage.setItem(COLD_OPEN_FLAG, "1");
    navigate("/positions", { replace: true });
  }, [location.pathname, navigate]);
  return null;
}

function AnalysisShell() {
  return (
    <div className="flex flex-col h-full">
      <TickerTape />
      <DashboardHeader />
      <TopNavBar />
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/market" element={<MarketPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/signal" element={<SignalPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
