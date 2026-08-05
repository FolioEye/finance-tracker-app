import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

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

  it("renders the sign-in heading and both provider buttons", () => {
    renderLoginPage();

    expect(screen.getByText("Sign in to FinTrack")).toBeInTheDocument();
    expect(screen.getByTestId("google-signin-button")).toBeInTheDocument();
    expect(screen.getByTestId("apple-signin-button")).toBeInTheDocument();
  });

  it("does not render an error message before any sign-in attempt", () => {
    renderLoginPage();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
