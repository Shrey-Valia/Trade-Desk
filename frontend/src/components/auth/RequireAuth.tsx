import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useMe } from "@/hooks/useAuth";

/**
 * Route guard for everything inside the rail shell. While the session
 * probe is in flight we render a blank tier-0 screen (sub-second,
 * avoids a flash of either state); a 401 bounces to /signin carrying
 * the intended destination.
 */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();

  if (me.isPending) {
    return <div className="min-h-screen bg-tier-0" />;
  }
  if (me.isError) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/signin?next=${next}`} replace />;
  }
  return <Outlet />;
}
