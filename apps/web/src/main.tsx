import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { bootstrapSession } from "./api/auth";
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

// FINTRACK-60-AC2: fire the silent refresh before React mounts. We do NOT
// await it here -- awaiting would delay first paint on every load,
// including for signed-out visitors. ProtectedRoute holds the redirect
// decision via bootstrapState instead, so the app renders immediately and
// only the protected content waits.
//
// Called outside the component tree deliberately: React 18 StrictMode
// double-invokes effects in development, and refreshSessionOnce()'s shared
// promise would collapse a double call anyway.
//
// Ordering note: this runs AFTER the E2E seam above, so a Playwright spec
// that seeds the store directly still wins -- bootstrapSession()'s own
// refresh will 401 with no cookie and only call markBootstrapped(), which
// does not clear a session the spec already set.
void bootstrapSession();

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
