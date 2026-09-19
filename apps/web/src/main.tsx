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
//
// FINTRACK-66: the seam now also APPLIES a session that the harness injected
// before this script ran. The access token lives in memory only (see
// store/authStore.ts -- no persist middleware, by design), so a session poked
// into the store from a test evaporates on the next page.goto, which is a real
// document navigation. Playwright's addInitScript runs before page scripts on
// every document load, so __E2E_SESSION__ is already on window by the time this
// module evaluates and the session survives navigation without the app storing
// anything in localStorage/sessionStorage.
//
// Both halves stay inside the same guard: still nothing here can reach a
// production bundle, and window.__E2E_SESSION__ is inert in one.
if (!import.meta.env.PROD && import.meta.env.VITE_E2E_TEST_MODE === "true") {
  const testWindow = window as unknown as {
    __E2E_AUTH_STORE__: typeof useAuthStore;
    __E2E_SESSION__?: { accessToken: string; userId: string; email: string };
  };

  testWindow.__E2E_AUTH_STORE__ = useAuthStore;

  if (testWindow.__E2E_SESSION__) {
    useAuthStore.getState().setSession(testWindow.__E2E_SESSION__);
  }
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
