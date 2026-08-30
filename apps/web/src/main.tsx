import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { queryClient } from "./lib/queryClient";
import { useAuthStore } from "./store/authStore";
import "./styles/index.css";

// E2E test seam only -- never active unless VITE_E2E_TEST_MODE is explicitly
// set (Playwright's own webServer env, not a normal dev/build run). Lets
// Playwright specs seed an authenticated session directly instead of driving
// a real Google OAuth popup, which can't be automated in CI. Gated on both
// this flag AND import.meta.env.PROD being false as a second guard against
// ever shipping this in a production bundle.
if (!import.meta.env.PROD && import.meta.env.VITE_E2E_TEST_MODE === "true") {
  (window as unknown as { __E2E_AUTH_STORE__: typeof useAuthStore }).__E2E_AUTH_STORE__ =
    useAuthStore;
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found -- check index.html");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
