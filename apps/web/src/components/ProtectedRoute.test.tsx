import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "../store/authStore";
import { ProtectedRoute } from "./ProtectedRoute";

function TestApp() {
  return (
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route path="/login" element={<div data-testid="login-page">Login</div>} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <div data-testid="dashboard-content">Secret dashboard content</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProtectedRoute (security scenario shared by FINTRACK-52/57/58)", () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: null, userId: null, email: null });
  });

  afterEach(() => {
    useAuthStore.setState({ accessToken: null, userId: null, email: null });
  });

  it("redirects to /login when unauthenticated, with no protected content ever rendered", () => {
    render(<TestApp />);

    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    // Not just "eventually removed" -- it must never mount at all, since
    // ProtectedRoute returns <Navigate> synchronously instead of rendering
    // children first and redirecting after (no content flash).
    expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
  });

  it("renders the protected content when an access token is present", () => {
    useAuthStore.setState({ accessToken: "valid-token", userId: "u1", email: "user@example.com" });

    render(<TestApp />);

    expect(screen.getByTestId("dashboard-content")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });
});
