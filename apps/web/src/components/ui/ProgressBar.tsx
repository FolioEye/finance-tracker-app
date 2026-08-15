interface ProgressBarProps {
  /** 0-100+. Deliberately not clamped at 100 -- FINTRACK-55 AC7 requires
   * over-budget spend to show its true percentage (e.g. 125%), not a
   * value silently capped at the container width. */
  percent: number;
  isOverBudget?: boolean;
  label?: string;
}

export function ProgressBar({ percent, isOverBudget = false, label }: ProgressBarProps) {
  const clampedWidth = Math.min(Math.max(percent, 0), 100);
  const barColor = isOverBudget
    ? "bg-rose-500"
    : percent >= 85
      ? "bg-amber-500"
      : "bg-emerald-500";

  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
    >
      <div
        className={`h-full rounded-full transition-all ${barColor}`}
        style={{ width: `${clampedWidth}%` }}
      />
    </div>
  );
}
