import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "../lib/queryClient";
import { LoginPage } from "./LoginPage";

function renderLoginPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <LoginPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders the sign-in heading and the Google button", () => {
    renderLoginPage();

    expect(screen.getByText("Sign in to FinTrack")).toBeInTheDocument();
    expect(screen.getByTestId("google-signin-button")).toBeInTheDocument();
  });

  it("renders the Apple button when VITE_APPLE_CLIENT_ID is configured", () => {
    vi.stubEnv("VITE_APPLE_CLIENT_ID", "com.fintrack.web");
    renderLoginPage();

    expect(screen.getByTestId("apple-signin-button")).toBeInTheDocument();
  });

  it("hides the Apple button instead of crashing when VITE_APPLE_CLIENT_ID is not configured (FINTRACK-38 regression, 2026-08-09)", () => {
    vi.stubEnv("VITE_APPLE_CLIENT_ID", "");
    renderLoginPage();

    expect(screen.getByText("Sign in to FinTrack")).toBeInTheDocument();
    expect(screen.queryByTestId("apple-signin-button")).not.toBeInTheDocument();
  });

  it("does not render an error message before any sign-in attempt", () => {
    renderLoginPage();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
