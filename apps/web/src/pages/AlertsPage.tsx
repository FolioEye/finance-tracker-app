import { useAlerts, useDismissAlert, type Alert } from "../api/alerts";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";
import { formatDate } from "../lib/format";

function alertMessage(alert: Alert): string {
  if (alert.alert_type === "LARGE_TRANSACTION") {
    return `A larger-than-usual transaction was recorded in ${alert.category}.`;
  }
  return `${alert.category} spending has crossed ${alert.threshold_pct ?? ""}% of its budget.`;
}

function AlertRow({ alert }: { alert: Alert }) {
  // Each row owns its own mutation instance so a failed dismiss on one
  // alert can't be confused with another row's pending/error state, and
  // (FINTRACK-57 dismiss-fails scenario) the alert only ever disappears
  // from the list via the shared query cache invalidated on a *successful*
  // dismiss -- never optimistically, so a 500 leaves it exactly where it was.
  const dismissAlert = useDismissAlert();
  const isDismissed = Boolean(alert.dismissed_at);

  return (
    <li
      data-testid={`alert-row-${alert.id}`}
      className="flex flex-wrap items-start justify-between gap-3 px-4 py-4 sm:px-6"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {!isDismissed && (
            <span className="h-2 w-2 shrink-0 rounded-full bg-brand-600" aria-hidden="true" />
          )}
          <Badge tone="warning">{alert.alert_type.replace(/_/g, " ")}</Badge>
        </div>
        <p className="mt-1 text-sm font-medium text-slate-900">{alertMessage(alert)}</p>
        <p className="text-xs text-slate-500">{formatDate(alert.period_start)}</p>
      </div>
      {!isDismissed && (
        <div className="flex flex-col items-end gap-1">
          <Button
            data-testid={`dismiss-alert-${alert.id}`}
            variant="secondary"
            isLoading={dismissAlert.isPending}
            onClick={() => dismissAlert.mutate(alert.id)}
          >
            Dismiss
          </Button>
          {dismissAlert.isError && (
            <button
              type="button"
              data-testid={`retry-dismiss-${alert.id}`}
              onClick={() => dismissAlert.mutate(alert.id)}
              className="text-xs font-medium text-rose-600 hover:underline"
            >
              Dismiss failed -- retry
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function AlertsPage() {
  const { data, isLoading } = useAlerts(false);

  return (
    <AppShell title="Alerts">
      {isLoading ? (
        <Spinner label="Loading alerts" />
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState
          data-testid="alerts-empty-state"
          title="No alerts right now"
          description="You'll see budget and spending alerts here as they come up."
        />
      ) : (
        <Card className="overflow-hidden !p-0">
          <ul data-testid="alerts-list" className="divide-y divide-slate-100">
            {data?.items.map((alert) => <AlertRow key={alert.id} alert={alert} />)}
          </ul>
        </Card>
      )}
    </AppShell>
  );
}
