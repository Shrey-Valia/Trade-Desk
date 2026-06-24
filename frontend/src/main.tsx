import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { Toaster } from "@/components/toast/Toaster";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 15_000,
      // Smart retry: never retry a 4xx — it's a terminal answer (the 0DTE
      // chain's 409 "No 0DTE for X today", an off-hours 404, an auth 401).
      // Retrying only delays the empty state and, for upstream Alpaca 429s,
      // fans one poll into 4 requests. Allow a single retry for transient
      // 5xx / network failures. (Mutations don't retry by default.)
      retry: (failureCount, error) => {
        const status = (error as { status?: number })?.status;
        if (status != null && status >= 400 && status < 500) return false;
        return failureCount < 1;
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <Toaster />
    </QueryClientProvider>
  </React.StrictMode>,
);
