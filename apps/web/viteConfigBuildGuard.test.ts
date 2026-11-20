// @vitest-environment node
// (vite.config.ts pulls in Vite/esbuild, which reject jsdom's TextEncoder.)
//
// FINTRACK-80: proves the guard is wired into vite.config.ts for `vite build`
// only (FINTRACK-80-AC1) and stays out of the dev server and vitest
// (FINTRACK-80-AC4). The fact that this very file runs under vitest with the
// placeholder stubbed below is itself the AC4 "vitest starts" evidence.
import type { ConfigEnv, UserConfigFnObject } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

import viteConfig from "./vite.config";

const configFn = viteConfig as unknown as UserConfigFnObject;

function runConfig(env: Pick<ConfigEnv, "command" | "mode">): void {
  configFn({ ...env, isSsrBuild: false, isPreview: false });
}

describe("vite.config.ts build guard wiring", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("fails `vite build` when the API base URL is a placeholder", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://placeholder.railway.app");
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "1234567890-abcdefghijklmnop.apps.googleusercontent.com");
    expect(() => runConfig({ command: "build", mode: "production" })).toThrow(
      /VITE_API_BASE_URL: placeholder value/,
    );
  });

  it("does not run the check for the dev server", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://placeholder.railway.app");
    expect(() => runConfig({ command: "serve", mode: "development" })).not.toThrow();
  });

  it("does not run the check for vitest", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://placeholder.railway.app");
    expect(() => runConfig({ command: "serve", mode: "test" })).not.toThrow();
  });
});
