import { Suspense, lazy, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth } from "@/components/auth/RequireAuth";
import { RailShell } from "@/components/layout/RailShell";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useMe } from "@/hooks/useAuth";
import { useUserSettings } from "@/stores/userSettings";

// Route-level code splitting. Each page (and its heavy transitive deps —
// charts, analytics, the drawing layer) lands in its own chunk that's only
// fetched when the user navigates there, dropping the eager main bundle well
// under Vite's 500 kB warning. The always-on shell (auth gate, rail) stays
// eager so the first paint has no extra round-trip.
const AccountsPage = lazy(() =>
  import("@/pages/AccountsPage").then((m) => ({ default: m.AccountsPage })),
);
const AnalyticsPage = lazy(() =>
  import("@/pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })),
);
const DashboardPage = lazy(() =>
  import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const JournalPage = lazy(() =>
  import("@/pages/JournalPage").then((m) => ({ default: m.JournalPage })),
);
const LandingPage = lazy(() =>
  import("@/pages/LandingPage").then((m) => ({ default: m.LandingPage })),
);
const NewCombinePage = lazy(() =>
  import("@/pages/NewCombinePage").then((m) => ({ default: m.NewCombinePage })),
);
const PayoutsPage = lazy(() =>
  import("@/pages/PayoutsPage").then((m) => ({ default: m.PayoutsPage })),
);
const PositionsPage = lazy(() =>
  import("@/pages/PositionsPage").then((m) => ({ default: m.PositionsPage })),
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);
const SignInPage = lazy(() =>
  import("@/pages/SignInPage").then((m) => ({ default: m.SignInPage })),
);
const SignUpPage = lazy(() =>
  import("@/pages/SignUpPage").then((m) => ({ default: m.SignUpPage })),
);

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
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<RootGate />} />
            <Route
              path="/signin"
              element={<GuestOnly page={<SignInPage />} authedTo="/dashboard" />}
            />
            <Route
              path="/signup"
              element={
                <GuestOnly page={<SignUpPage />} authedTo="/combines/new" />
              }
            />
            <Route element={<RequireAuth />}>
              <Route element={<RailShell />}>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/accounts" element={<AccountsPage />} />
                <Route path="/payouts" element={<PayoutsPage />} />
                <Route path="/positions" element={<PositionsPage />} />
                <Route path="/combines/new" element={<NewCombinePage />} />
                <Route path="/journal" element={<JournalPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

/** Suspense fallback while a lazily-loaded route chunk is fetched. Matches
 *  the auth-gate placeholders (bare tier-0 fill) so the swap is invisible
 *  on fast connections and unobtrusive on slow ones. */
function RouteFallback() {
  return <div className="min-h-screen bg-tier-0" />;
}

/** "/" — authed users go to the management dashboard; guests get the
 * marketing landing page. */
function RootGate() {
  const me = useMe();
  if (me.isPending) return <div className="min-h-screen bg-tier-0" />;
  return me.isSuccess ? <Navigate to="/dashboard" replace /> : <LandingPage />;
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
