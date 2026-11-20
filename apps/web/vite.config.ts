/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

import { assertBuildEnv } from "./buildEnvGuard";

// Config vars the production build must not silently proceed without.
// FINTRACK-47: previously, an unset VITE_API_BASE_URL was baked into the
// bundle as the literal string "undefined" with a clean exit 0 -- every
// request from the shipped app would then fail against that literal
// string as a base URL, with no build-time signal anything was wrong.
//
// VITE_GOOGLE_CLIENT_ID added here after a related incident (2026-08-09):
// it was never gated at all, so a missing value shipped as `undefined`
// straight into Google's SDK. VITE_APPLE_CLIENT_ID/VITE_APPLE_REDIRECT_URI
// are deliberately NOT required here -- Apple sign-in requires a paid
// Apple Developer Program enrollment ($99/yr) that may not exist yet, so
// LoginPage.tsx is written to gracefully hide the Apple button instead of
// crashing when those are absent. Google has no such paywall, so it stays
// a hard build-time requirement like the API base URL.
//
// FINTRACK-80 (follows the 2026-08-30 live incident): the presence-only
// check passed a VITE_API_URL secret set to the literal placeholder
// "https://placeholder.railway.app". The guard now also rejects values
// matching a fixed placeholder deny-list -- see buildEnvGuard.ts for the
// rule (FINTRACK-80-AC5). Still not done: a post-build smoke test that
// actually calls the configured API URL (out of scope for FINTRACK-80).
// The list of required vars lives in buildEnvGuard.ts as
// REQUIRED_BUILD_ENV_VARS.

export default defineConfig(({ command, mode }) => {
  if (command === "build") {
    // loadEnv reads both .env* files and already-exported environment
    // vars (the latter is how CI / Release Pro's deploy pipeline actually
    // supplies this) for the current mode, with already-exported vars
    // taking precedence -- the same source of truth the app's real config
    // loading already uses. envDir is "." rather than a Node process.cwd()
    // call: `npm run build` always runs with cwd already set to apps/web,
    // so "." resolves to the same directory without depending on Node's
    // global types being available to this client-adjacent TS project.
    // Scoped to command === "build" only, so `npm run dev` and vitest
    // test runs aren't forced to have production config present just to
    // start (FINTRACK-80-AC4).
    assertBuildEnv(loadEnv(mode, ".", ""));
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test/setup.ts",
    },
  };
});
