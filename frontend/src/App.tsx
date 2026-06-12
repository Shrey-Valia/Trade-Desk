import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "@/components/auth/RequireAuth";
import { RailShell } from "@/components/layout/RailShell";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { JournalPage } from "@/pages/JournalPage";
import { NewCombinePage } from "@/pages/NewCombinePage";
import { PositionsPage } from "@/pages/PositionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SignInPage } from "@/pages/SignInPage";
import { SignUpPage } from "@/pages/SignUpPage";
import { WatchlistPage } from "@/pages/WatchlistPage";
import { useMe } from "@/hooks/useAuth";
import { useUserSettings } from "@/stores/userSettings";

/**
 * Top-level routing — multi-user shell.
 *
 *   /signin, /signup   standalone auth pages (no rail)
 *   rail shell         everything else, behind RequireAuth
 *   /                  logged-in → terminal; logged-out → /signin
 *                      (becomes the marketing landing page later)
 *
 * Retired Analysis-mode pages remain on disk, unrouted, for later
 * cannibalization. Unknown URLs funnel to "/".
 */
export default function App() {
  // Apply the background-gradient preference at the document level so
  // the radial in index.css can opt out via [data-bg-gradient="off"].
  const bgGradient = useUserSettings((s) => s.bgGradient);
  useEffect(() => {
    document.documentElement.dataset.bgGradient = bgGradient ? "on" : "off";
  }, [bgGradient]);
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootGate />} />
        <Route
          path="/signin"
          element={<GuestOnly page={<SignInPage />} authedTo="/positions" />}
        />
        <Route
          path="/signup"
          element={<GuestOnly page={<SignUpPage />} authedTo="/combines/new" />}
        />
        <Route element={<RequireAuth />}>
          <Route element={<RailShell />}>
            <Route path="/positions" element={<PositionsPage />} />
            <Route path="/combines/new" element={<NewCombinePage />} />
            <Route path="/journal" element={<JournalPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

/** "/" — authed users go to the terminal; guests to sign-in. The
 * marketing landing page takes over this slot in a later phase. */
function RootGate() {
  const me = useMe();
  if (me.isPending) return <div className="min-h-screen bg-tier-0" />;
  return me.isSuccess ? (
    <Navigate to="/positions" replace />
  ) : (
    <Navigate to="/signin" replace />
  );
}

/**
 * Auth pages bounce signed-in users into the app. The bounce honors
 * ?next= and otherwise uses the page's natural destination — this is
 * ALSO the post-submit redirect path: the signin/signup mutation sets
 * the me-cache, this component re-renders authed, and the Navigate
 * here wins. (The forms' own navigate() is a no-op backup.)
 */
function GuestOnly({
  page,
  authedTo,
}: {
  page: React.ReactElement;
  authedTo: string;
}) {
  const me = useMe();
  const next = new URLSearchParams(window.location.search).get("next");
  if (me.isPending) return <div className="min-h-screen bg-tier-0" />;
  return me.isSuccess ? <Navigate to={next || authedTo} replace /> : page;
}
