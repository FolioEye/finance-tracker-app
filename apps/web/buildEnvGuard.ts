// Build-time guard for required production config (FINTRACK-47, FINTRACK-80).
//
// Kept separate from vite.config.ts so the rule is a pure function that can be
// unit-tested without loading Vite or its plugins. It has no Node or Vite
// imports on purpose: tsconfig.node.json compiles it alongside vite.config.ts.
//
// FINTRACK-47 made the production build fail when a required var is absent.
// FINTRACK-80 closes the gap that guard left open (live incident 2026-08-30):
// a value that is *present but fake*, e.g. "https://placeholder.railway.app",
// passed the presence check and shipped. Values are now also matched against a
// fixed deny-list (FINTRACK-80-AC5). This is a deny-list, not a reachability
// check -- it catches obvious placeholders, not every wrong value.

export const REQUIRED_BUILD_ENV_VARS = ["VITE_API_BASE_URL", "VITE_GOOGLE_CLIENT_ID"] as const;

export type RequiredBuildEnvVar = (typeof REQUIRED_BUILD_ENV_VARS)[number];

// FINTRACK-80-AC5. Matching runs on the value after trim + lower-case. The
// rule is fixed per pattern; there is no other matching mode.
//
// Rejected if the pattern appears anywhere in the value.
const SUBSTRING_PLACEHOLDER_PATTERNS: readonly string[] = ["placeholder", "changeme", "your-", "example"];
// Rejected only if the entire value equals the pattern ("" covers a value
// made only of whitespace). "1234-todolist.apps..." is NOT a match.
const WHOLE_VALUE_PLACEHOLDER_PATTERNS: readonly string[] = ["undefined", "null", "todo", "xxx", ""];

export type BuildEnvProblemReason = "missing" | "placeholder";

export interface BuildEnvProblem {
  readonly key: string;
  readonly reason: BuildEnvProblemReason;
}

export class BuildConfigError extends Error {
  readonly problems: readonly BuildEnvProblem[];

  constructor(problems: readonly BuildEnvProblem[]) {
    super(formatBuildEnvProblems(problems));
    this.name = "BuildConfigError";
    this.problems = problems;
  }
}

export function isPlaceholderValue(value: string): boolean {
  const normalised = value.trim().toLowerCase();
  if (WHOLE_VALUE_PLACEHOLDER_PATTERNS.includes(normalised)) {
    return true;
  }
  return SUBSTRING_PLACEHOLDER_PATTERNS.some((pattern) => normalised.includes(pattern));
}

// An unset var, or one set to exactly "" (e.g. `VITE_API_BASE_URL=` in a .env
// file), is "missing" -- the FINTRACK-47 behaviour, unchanged. Anything else
// that matches the deny-list is "placeholder", including whitespace-only.
function classify(value: string | undefined): BuildEnvProblemReason | null {
  if (value === undefined || value === "") {
    return "missing";
  }
  return isPlaceholderValue(value) ? "placeholder" : null;
}

// Returns every problem, in `keys` order, so one failed build reports all of
// them (FINTRACK-80-AC2) instead of making the operator fix them one at a time.
export function findBuildEnvProblems(
  env: Readonly<Record<string, string | undefined>>,
  keys: readonly string[] = REQUIRED_BUILD_ENV_VARS,
): BuildEnvProblem[] {
  const problems: BuildEnvProblem[] = [];
  for (const key of keys) {
    const reason = classify(env[key]);
    if (reason !== null) {
      problems.push({ key, reason });
    }
  }
  return problems;
}

// Names each offending variable and why. NEVER includes the value: a rejected
// value can still carry a secret (e.g. a token in a query string), and build
// logs are widely readable (FINTRACK-80-AC2).
export function formatBuildEnvProblems(problems: readonly BuildEnvProblem[]): string {
  const lines = problems.map(({ key, reason }) =>
    reason === "missing" ? `  - ${key}: missing` : `  - ${key}: placeholder value`,
  );
  return (
    "Invalid required config for production build (values are not shown):\n" +
    `${lines.join("\n")}\n` +
    "Set real values before running `npm run build` -- see apps/web/.env.example."
  );
}

export function assertBuildEnv(
  env: Readonly<Record<string, string | undefined>>,
  keys: readonly string[] = REQUIRED_BUILD_ENV_VARS,
): void {
  const problems = findBuildEnvProblems(env, keys);
  if (problems.length > 0) {
    throw new BuildConfigError(problems);
  }
}
