import { describe, expect, it } from "vitest";

import { formatCurrency, formatDate, formatPercent } from "./format";

describe("formatCurrency", () => {
  it("formats a decimal string as USD", () => {
    expect(formatCurrency("42.5")).toBe("$42.50");
  });

  it("formats a plain number", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });

  it("falls back to -- for non-numeric input", () => {
    expect(formatCurrency("not-a-number")).toBe("--");
  });
});

describe("formatDate", () => {
  it("formats an ISO date string", () => {
    expect(formatDate("2026-03-05")).toBe("Mar 5, 2026");
  });

  it("falls back to the raw string for an invalid date", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("formatPercent", () => {
  it("rounds and appends a percent sign", () => {
    expect(formatPercent("62.7")).toBe("63%");
  });

  it("returns -- for null", () => {
    expect(formatPercent(null)).toBe("--");
  });
});
