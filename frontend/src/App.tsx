import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { DashboardHeader } from "@/components/layout/DashboardHeader";
import { TopNavBar } from "@/components/layout/TopNavBar";
import { TickerTape } from "@/components/tradingview/TickerTape";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { MarketPage } from "@/pages/MarketPage";
import { NewsPage } from "@/pages/NewsPage";
import { PositionsPage } from "@/pages/PositionsPage";
import { SignalPage } from "@/pages/SignalPage";

const COLD_OPEN_FLAG = "td:cold-open-routed";

export default function App() {
  return (
    <BrowserRouter>
      <ColdOpenRedirect />
      <Routes>
        <Route path="/positions" element={<PositionsPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/*" element={<AnalysisShell />} />
      </Routes>
    </BrowserRouter>
  );
}

/**
 * First-load route hijack — sends a brand-new visitor straight to the
 * Trade Desk shell so the differentiated chart-first surface is the
 * first impression. We set a localStorage flag after the redirect so
 * subsequent loads respect whatever URL the user has actually navigated
 * to. Bookmarks to `/`, `/market`, etc. work normally after the first
 * visit.
 */
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
