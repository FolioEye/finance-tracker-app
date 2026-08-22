import { useState } from "react";

import {
  useBudgetOverview,
  useCreateBudget,
  useDeleteBudget,
  useUpdateBudget,
  type BudgetOverviewItem,
} from "../api/budgets";
import { ApiError } from "../api/client";
import { AppShell } from "../components/layout/AppShell";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { FormField } from "../components/ui/FormField";
import { INPUT_CLASSES } from "../components/ui/inputStyles";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Spinner } from "../components/ui/Spinner";
import { formatCurrency, formatPercent } from "../lib/format";

function validateLimit(value: string): string | null {
  const amount = Number(value);
  if (!value || Number.isNaN(amount)) {
    return "Enter a valid amount.";
  }
  // FINTRACK-55 AC2/negative-limit scenario -- mirrors
  // domain.models.budget.InvalidBudgetAmountError server-side.
  if (amount <= 0) {
    return "Budget must be a positive amount.";
  }
  return null;
}

function SetBudgetForm({
  category,
  onCancel,
  onSaved,
}: {
  category: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [limit, setLimit] = useState("");
  const [error, setError] = useState<string | null>(null);
  const createBudget = useCreateBudget();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const validationError = validateLimit(limit);
    setError(validationError);
    if (validationError) {
      return;
    }
    try {
      await createBudget.mutateAsync({ category, monthly_limit: limit });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 flex flex-wrap items-end gap-2">
      <div className="w-40">
        <FormField label={`Monthly limit for ${category}`} htmlFor={`limit-${category}`} error={error ?? undefined}>
          <input
            id={`limit-${category}`}
            type="text"
            inputMode="decimal"
            className={INPUT_CLASSES}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="500.00"
          />
        </FormField>
      </div>
      <Button type="submit" data-testid={`save-new-budget-${category}`} isLoading={createBudget.isPending}>
        Save
      </Button>
      <Button type="button" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function EditLimitForm({
  item,
  onCancel,
  onSaved,
}: {
  item: BudgetOverviewItem;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [limit, setLimit] = useState(item.monthly_limit ?? "");
  const [error, setError] = useState<string | null>(null);
  const updateBudget = useUpdateBudget();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const validationError = validateLimit(limit);
    setError(validationError);
    if (validationError || !item.budget_id) {
      return;
    }
    try {
      await updateBudget.mutateAsync({ id: item.budget_id, monthly_limit: limit });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 flex flex-wrap items-end gap-2">
      <div className="w-40">
        <FormField label="Monthly limit" htmlFor={`edit-limit-${item.budget_id}`} error={error ?? undefined}>
          <input
            id={`edit-limit-${item.budget_id}`}
            type="text"
            inputMode="decimal"
            className={INPUT_CLASSES}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
          />
        </FormField>
      </div>
      <Button type="submit" data-testid={`save-edit-budget-${item.category}`} isLoading={updateBudget.isPending}>
        Save
      </Button>
      <Button type="button" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </form>
  );
}

function BudgetRow({ item }: { item: BudgetOverviewItem }) {
  const [isEditing, setIsEditing] = useState(false);
  const [isSettingBudget, setIsSettingBudget] = useState(false);
  const deleteBudget = useDeleteBudget();
  const hasBudget = item.monthly_limit !== null;

  return (
    <Card data-testid={`budget-row-${item.category}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-slate-900">{item.category}</p>
          <p className="text-sm text-slate-500">Spent {formatCurrency(item.spent)}</p>
        </div>
        {hasBudget ? (
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setIsEditing((v) => !v)}>
              Edit
            </Button>
            <Button
              variant="ghost"
              className="text-rose-600 hover:bg-rose-50"
              onClick={() => {
                if (item.budget_id && window.confirm(`Delete the ${item.category} budget?`)) {
                  deleteBudget.mutate(item.budget_id);
                }
              }}
            >
              Delete
            </Button>
          </div>
        ) : (
          <Button
            variant="secondary"
            data-testid={`set-budget-${item.category}`}
            onClick={() => setIsSettingBudget((v) => !v)}
          >
            Set budget
          </Button>
        )}
      </div>

      {hasBudget && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500">of {formatCurrency(item.monthly_limit as string)}</span>
            <span className={item.is_over_budget ? "font-semibold text-rose-600" : "text-slate-700"}>
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
        </div>
      )}

      {isEditing && hasBudget && (
        <EditLimitForm item={item} onCancel={() => setIsEditing(false)} onSaved={() => setIsEditing(false)} />
      )}
      {isSettingBudget && !hasBudget && (
        <SetBudgetForm
          category={item.category}
          onCancel={() => setIsSettingBudget(false)}
          onSaved={() => setIsSettingBudget(false)}
        />
      )}
    </Card>
  );
}

function NewBudgetForm({ onDone }: { onDone: () => void }) {
  const [category, setCategory] = useState("");
  const [limit, setLimit] = useState("");
  const [error, setError] = useState<string | null>(null);
  const createBudget = useCreateBudget();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!category.trim()) {
      setError("Category is required.");
      return;
    }
    const validationError = validateLimit(limit);
    setError(validationError);
    if (validationError) {
      return;
    }
    try {
      await createBudget.mutateAsync({ category: category.trim(), monthly_limit: limit });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  }

  return (
    <Card>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <FormField label="Category" htmlFor="new-budget-category">
            <input
              id="new-budget-category"
              data-testid="new-budget-category-input"
              type="text"
              className={INPUT_CLASSES}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Entertainment"
            />
          </FormField>
        </div>
        <div className="w-40">
          <FormField label="Monthly limit" htmlFor="new-budget-limit">
            <input
              id="new-budget-limit"
              data-testid="new-budget-limit-input"
              type="text"
              inputMode="decimal"
              className={INPUT_CLASSES}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="150.00"
            />
          </FormField>
        </div>
        <Button type="submit" data-testid="submit-new-budget" isLoading={createBudget.isPending}>
          Add budget
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose-600">
          {error}
        </p>
      )}
    </Card>
  );
}

export function BudgetsPage() {
  const { data, isLoading } = useBudgetOverview();
  const [isAddingNew, setIsAddingNew] = useState(false);

  return (
    <AppShell
      title="Budgets"
      actions={
        !isAddingNew && (
          <Button data-testid="add-budget-button" onClick={() => setIsAddingNew(true)}>
            Add budget
          </Button>
        )
      }
    >
      <div className="space-y-4">
        {isAddingNew && <NewBudgetForm onDone={() => setIsAddingNew(false)} />}

        {isLoading ? (
          <Spinner label="Loading budgets" />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState
            data-testid="budgets-empty-state"
            title="No budgets set yet"
            description="Set a monthly limit for a category to start tracking your budget health."
            action={!isAddingNew ? <Button onClick={() => setIsAddingNew(true)}>Add budget</Button> : undefined}
          />
        ) : (
          <div data-testid="budgets-list" className="space-y-3">
            {data?.items.map((item) => <BudgetRow key={item.category} item={item} />)}
          </div>
        )}
      </div>
    </AppShell>
  );
}
