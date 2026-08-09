/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Config vars the production build must not silently proceed without.
// FINTRACK-47: previously, an unset VITE_API_BASE_URL was baked into the
// bundle as the literal string "undefined" with a clean exit 0 -- every
// request from the shipped app would then fail against that literal
// string as a base URL, with no build-time signal anything was wrong.
const REQUIRED_BUILD_ENV_VARS = ["VITE_API_BASE_URL"] as const;

export default defineConfig(({ command, mode }) => {
  if (command === "build") {
    // loadEnv reads both .env* files and already-exported process.env
    // vars (the latter is how CI / Release Pro's deploy pipeline actually
    // supplies this) for the current mode, with process.env taking
    // precedence -- the same source of truth the app's real config
    // loading already uses. Scoped to command === "build" only, so
    // `npm run dev` and vitest test runs aren't forced to have
    // production config present just to start.
    const env = loadEnv(mode, process.cwd(), "");
    const missing = REQUIRED_BUILD_ENV_VARS.filter((key) => !env[key]);
    if (missing.length > 0) {
      throw new Error(
        `Missing required config for production build: ${missing.join(", ")}. ` +
          "Set these before running `npm run build` -- see apps/web/.env.example.",
      );
    }
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
