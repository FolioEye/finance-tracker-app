import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  it("exposes the real (uncapped) percent via aria-valuenow even when over 100", () => {
    render(<ProgressBar percent={125} isOverBudget label="Dining budget usage" />);
    const bar = screen.getByRole("progressbar", { name: "Dining budget usage" });
    expect(bar).toHaveAttribute("aria-valuenow", "125");
  });

  it("clamps the visual width to 100% without clamping the reported value", () => {
    render(<ProgressBar percent={125} isOverBudget />);
    const bar = screen.getByRole("progressbar");
    const fill = bar.firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("100%");
  });

  it("renders a normal fill for under-budget usage", () => {
    render(<ProgressBar percent={60} />);
    const bar = screen.getByRole("progressbar");
    const fill = bar.firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("60%");
  });
});
