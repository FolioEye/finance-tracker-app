import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { bootstrapSession } from "./api/auth";
import { queryClient } from "./lib/queryClient";
import "./styles/index.css";

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
