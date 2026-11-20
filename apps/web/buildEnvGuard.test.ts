// FINTRACK-80: one test per Gherkin scenario in
// tests/features/FINTRACK-80-reject-placeholder-build-env.feature.
// All values are obviously fake; never put a real credential here.
import { describe, expect, it } from "vitest";

import {
  BuildConfigError,
  assertBuildEnv,
  findBuildEnvProblems,
  formatBuildEnvProblems,
} from "./buildEnvGuard";

const REAL_API_URL = "https://api.fintrack.app";
const REAL_CLIENT_ID = "1234567890-abcdefghijklmnop.apps.googleusercontent.com";

function buildError(env: Record<string, string | undefined>): BuildConfigError {
  try {
    assertBuildEnv(env);
  } catch (error) {
    if (error instanceof BuildConfigError) {
      return error;
    }
    throw error;
  }
  throw new Error("expected the build to fail, but it proceeded");
}

describe("FINTRACK-80 placeholder build-env guard", () => {
  // FINTRACK-80-AC1
  it("fails when the API base URL is a placeholder", () => {
    const error = buildError({
      VITE_API_BASE_URL: "https://placeholder.railway.app",
      VITE_GOOGLE_CLIENT_ID: REAL_CLIENT_ID,
    });
    expect(error.problems).toEqual([{ key: "VITE_API_BASE_URL", reason: "placeholder" }]);
    expect(error.message).toContain("VITE_API_BASE_URL: placeholder value");
  });

  // FINTRACK-80-AC3
  it("proceeds with real config values", () => {
    expect(() =>
      assertBuildEnv({ VITE_API_BASE_URL: REAL_API_URL, VITE_GOOGLE_CLIENT_ID: REAL_CLIENT_ID }),
    ).not.toThrow();
  });

  // FINTRACK-80-AC1, AC5 (part-of-value patterns)
  it.each([
    "your-client-id",
    "CHANGEME",
    "example-client-id",
    "1234567890-placeholder.apps.googleusercontent.com",
    "1234567890-changeme-abc.apps.googleusercontent.com",
  ])("rejects a value containing a part-of-value pattern: %s", (value) => {
    const error = buildError({ VITE_API_BASE_URL: REAL_API_URL, VITE_GOOGLE_CLIENT_ID: value });
    expect(error.problems).toEqual([{ key: "VITE_GOOGLE_CLIENT_ID", reason: "placeholder" }]);
  });

  // FINTRACK-80-AC1, AC5 (whole-value patterns)
  it.each(["undefined", "null", "TODO", "xxx"])(
    "rejects a value that is entirely a whole-value pattern: %s",
    (value) => {
      const error = buildError({ VITE_API_BASE_URL: REAL_API_URL, VITE_GOOGLE_CLIENT_ID: value });
      expect(error.problems).toEqual([{ key: "VITE_GOOGLE_CLIENT_ID", reason: "placeholder" }]);
    },
  );

  // FINTRACK-80-AC3, AC5 (whole-value patterns do not match inside a longer value)
  it.each([
    "1234567890-nullabcdefgh.apps.googleusercontent.com",
    "1234567890-todolist.apps.googleusercontent.com",
    "1234567890-xxxabcdef.apps.googleusercontent.com",
    "1234567890-undefinedabc.apps.googleusercontent.com",
  ])("does not reject a whole-value pattern inside a longer value: %s", (value) => {
    expect(() =>
      assertBuildEnv({ VITE_API_BASE_URL: REAL_API_URL, VITE_GOOGLE_CLIENT_ID: value }),
    ).not.toThrow();
  });

  // FINTRACK-80-AC1, AC5 (empty after trim)
  it("rejects a value of only spaces as a placeholder", () => {
    const error = buildError({ VITE_API_BASE_URL: REAL_API_URL, VITE_GOOGLE_CLIENT_ID: "    " });
    expect(error.problems).toEqual([{ key: "VITE_GOOGLE_CLIENT_ID", reason: "placeholder" }]);
  });

  // FINTRACK-80-AC5 (normalisation)
  it("is case-insensitive and ignores surrounding whitespace", () => {
    const problems = findBuildEnvProblems({
      VITE_API_BASE_URL: "  HTTPS://PlaceHolder.Railway.app  ",
      VITE_GOOGLE_CLIENT_ID: REAL_CLIENT_ID,
    });
    expect(problems).toEqual([{ key: "VITE_API_BASE_URL", reason: "placeholder" }]);
  });

  // FINTRACK-80-AC2
  it("reports every offending variable in one failure", () => {
    const error = buildError({
      VITE_API_BASE_URL: "https://placeholder.railway.app",
      VITE_GOOGLE_CLIENT_ID: "your-client-id",
    });
    expect(error.problems).toEqual([
      { key: "VITE_API_BASE_URL", reason: "placeholder" },
      { key: "VITE_GOOGLE_CLIENT_ID", reason: "placeholder" },
    ]);
    expect(error.message).toContain("VITE_API_BASE_URL: placeholder value");
    expect(error.message).toContain("VITE_GOOGLE_CLIENT_ID: placeholder value");
  });

  // FINTRACK-80-AC2
  it("reports an unset variable as missing, separately from a placeholder", () => {
    const error = buildError({ VITE_GOOGLE_CLIENT_ID: "your-client-id" });
    expect(error.problems).toEqual([
      { key: "VITE_API_BASE_URL", reason: "missing" },
      { key: "VITE_GOOGLE_CLIENT_ID", reason: "placeholder" },
    ]);
    expect(error.message).toContain("VITE_API_BASE_URL: missing");
    expect(error.message).toContain("VITE_GOOGLE_CLIENT_ID: placeholder value");
  });

  // FINTRACK-47 behaviour preserved: `KEY=` in a .env file is still "missing".
  it("treats an exactly-empty value as missing", () => {
    const problems = findBuildEnvProblems({ VITE_API_BASE_URL: "", VITE_GOOGLE_CLIENT_ID: REAL_CLIENT_ID });
    expect(problems).toEqual([{ key: "VITE_API_BASE_URL", reason: "missing" }]);
  });

  // FINTRACK-80-AC2 (security: never echo the value)
  it("never leaks the configured value in the error", () => {
    const secretish = "https://placeholder.railway.app/?key=FAKE-TOKEN-0000-NOT-A-REAL-SECRET";
    const error = buildError({ VITE_API_BASE_URL: secretish, VITE_GOOGLE_CLIENT_ID: REAL_CLIENT_ID });
    expect(error.message).not.toContain(secretish);
    expect(error.message).not.toContain("FAKE-TOKEN-0000-NOT-A-REAL-SECRET");
    expect(JSON.stringify(error.problems)).not.toContain("FAKE-TOKEN");
  });

  it("formats nothing extra beyond key and reason", () => {
    expect(formatBuildEnvProblems([{ key: "VITE_X", reason: "missing" }])).toContain("  - VITE_X: missing");
  });
});
