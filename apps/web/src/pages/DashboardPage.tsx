import { Link } from "react-router-dom";

import { useBudgetOverview } from "../api/budgets";
import { useRecordFollowThroughAction } from "../api/followThrough";
import { useSpendingInsights } from "../api/insights";
import { useWeeklyRecommendation } from "../api/recommendations";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Spinner } from "../components/ui/Spinner";
import { formatCurrency, formatPercent } from "../lib/format";

const RECOMMENDATION_TONE: Record<string, "warning" | "danger" | "brand" | "neutral"> = {
  BUDGET_RISK: "warning",
  SPENDING_SPIKE: "danger",
  NEW_SUBSCRIPTION: "brand",
  NEUTRAL: "neutral",
};

function RecommendationCard() {
  const { data, isLoading, isError } = useWeeklyRecommendation();
  const recordAction = useRecordFollowThroughAction();

  if (isLoading) {
    return (
      <Card>
        <Spinner label="Loading this week's recommendation" />
      </Card>
    );
  }

  // FINTRACK-52 AC3 / FINTRACK-58 AC2: a failed recommendation call must
  // never take the rest of the dashboard down with it.
  if (isError || !data) {
    return (
      <Card data-testid="recommendation-error">
        <p className="text-sm text-slate-500">Couldn't load this week's recommendation.</p>
      </Card>
    );
  }

  const isActionable = data.type !== "NEUTRAL";

  return (
    <Card data-testid="recommendation-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Badge tone={RECOMMENDATION_TONE[data.type] ?? "neutral"}>
            {data.type === "NEUTRAL" ? "All clear" : data.type.replace(/_/g, " ")}
          </Badge>
          <p className="mt-2 text-base font-medium text-slate-900">
            {data.type === "NEUTRAL" ? "You're on track this week" : data.message}
          </p>
          {data.deprioritization_reason && (
            <p className="mt-1 text-sm text-slate-500">{data.deprioritization_reason}</p>
          )}
        </div>
      </div>
      {isActionable && (
        <div className="mt-4 flex gap-2">
          <Button
            variant="secondary"
            data-testid="recommendation-mark-done"
            isLoading={recordAction.isPending}
            onClick={() =>
              recordAction.mutate({ recordId: data.follow_through_record_id, action: "done" })
            }
          >
            Mark as done
          </Button>
          <Button
            variant="ghost"
            data-testid="recommendation-ignore"
            isLoading={recordAction.isPending}
            onClick={() =>
              recordAction.mutate({ recordId: data.follow_through_record_id, action: "ignore" })
            }
          >
            Ignore
          </Button>
        </div>
      )}
    </Card>
  );
}

function TopBudgetsCard() {
  const { data, isLoading } = useBudgetOverview();

  if (isLoading) {
    return (
      <Card>
        <Spinner label="Loading budgets" />
      </Card>
    );
  }

  const withLimits = (data?.items ?? []).filter((item) => item.monthly_limit !== null);
  const top3 = [...withLimits]
    .sort((a, b) => Number(b.percent_used ?? 0) - Number(a.percent_used ?? 0))
    .slice(0, 3);

  if (top3.length === 0) {
    return (
      <Card>
        <p className="text-sm font-medium text-slate-900">Budget health</p>
        <p className="mt-2 text-sm text-slate-500">
          No budgets set yet.{" "}
          <Link to="/budgets" className="font-medium text-brand-600 hover:underline">
            Set your first budget
          </Link>
          .
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <p className="text-sm font-medium text-slate-900">Top budget categories</p>
      <ul className="mt-4 space-y-4">
        {top3.map((item) => (
          <li key={item.budget_id}>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-slate-700">{item.category}</span>
              <span className={item.is_over_budget ? "font-semibold text-rose-600" : "text-slate-500"}>
                {formatPercent(item.percent_used)}
              </span>
            </div>
            <div className="mt-1.5">
              <ProgressBar
                percent={Number(item.percent_used ?? 0)}
                isOverBudget={item.is_over_budget}
                label={`${item.category} budget usage`}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SpendSummaryCard() {
  const { data, isLoading } = useSpendingInsights();

  if (isLoading) {
    return (
      <Card>
        <Spinner label="Loading spend summary" />
      </Card>
    );
  }

  return (
    <Card>
      <p className="text-sm font-medium text-slate-500">This month's spend</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">
        {formatCurrency(data?.current_month_total ?? "0")}
      </p>
      {data && data.by_category.length > 0 && (
        <ul className="mt-4 space-y-2">
          {[...data.by_category]
            .sort((a, b) => Number(b.total) - Number(a.total))
            .slice(0, 4)
            .map((item) => (
              <li key={item.category} className="flex items-center justify-between text-sm">
                <span className="text-slate-600">{item.category}</span>
                <span className="font-medium text-slate-900">{formatCurrency(item.total)}</span>
              </li>
            ))}
        </ul>
      )}
    </Card>
  );
}

export function DashboardPage() {
  const { data: insights, isLoading: insightsLoading } = useSpendingInsights();
  const { data: budgets, isLoading: budgetsLoading } = useBudgetOverview();

  const isBrandNewUser =
    !insightsLoading &&
    !budgetsLoading &&
    (insights?.by_category.length ?? 0) === 0 &&
    (budgets?.items.length ?? 0) === 0;

  return (
    <AppShell title="Dashboard">
      {isBrandNewUser ? (
        <EmptyState
          data-testid="dashboard-empty-state"
          title="Welcome to FinTrack"
          description="You don't have any transactions yet. Add your first one to see your spending summary and budget health here."
          action={
            <Link to="/transactions">
              <Button>Add your first transaction</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <RecommendationCard />
          </div>
          <SpendSummaryCard />
          <TopBudgetsCard />
        </div>
      )}
    </AppShell>
  );
}
