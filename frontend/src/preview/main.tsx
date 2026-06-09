import React from "react";
import ReactDOM from "react-dom/client";

import { UIHarness } from "@/preview/UIHarness";
import "@/index.css";

/**
 * Standalone entry for the UI-primitive preview harness. Mounts ONLY the
 * harness — no router, no QueryClient, no live app. Served at
 * /ui-preview.html (see frontend/ui-preview.html) during `npm run dev`.
 */
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <UIHarness />
  </React.StrictMode>,
);
