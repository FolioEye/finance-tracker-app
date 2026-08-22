import { useMemo, useState } from "react";

import {
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
  useUpdateTransaction,
  type Transaction,
} from "../api/transactions";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { FormField } from "../components/ui/FormField";
import { INPUT_CLASSES } from "../components/ui/inputStyles";
import { Spinner } from "../components/ui/Spinner";
import { ApiError } from "../api/client";
import { formatCurrency, formatDate } from "../lib/format";

interface TransactionFormState {
  amount: string;
  category: string;
  transaction_date: string;
  note: string;
}

const EMPTY_FORM: TransactionFormState = {
  amount: "",
  category: "",
  transaction_date: new Date().toISOString().slice(0, 10),
  note: "",
};

function validate(form: TransactionFormState): string | null {
  const amountNumber = Number(form.amount);
  if (!form.amount || Number.isNaN(amountNumber)) {
    return "Amount must be a number.";
  }
  // FINTRACK-53 AC5 / negative-amount security scenario: rejected
  // client-side before any request is made, and the backend
  // (domain.models.transaction.InvalidAmountError) enforces the same rule
  // independently -- this is a UX shortcut, not the source of truth.
  if (amountNumber <= 0) {
    return "Amount must be a positive number.";
  }
  if (!form.category.trim()) {
    return "Category is required.";
  }
  if (!form.transaction_date) {
    return "Date is required.";
  }
  return null;
}

function TransactionForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial?: Transaction;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<TransactionFormState>(
    initial
      ? {
          amount: initial.amount,
          category: initial.category,
          transaction_date: initial.transaction_date,
          note: initial.note ?? "",
        }
      : EMPTY_FORM,
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const createTransaction = useCreateTransaction();
  const updateTransaction = useUpdateTransaction();
  const isSaving = createTransaction.isPending || updateTransaction.isPending;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const error = validate(form);
    setClientError(error);
    if (error) {
      return;
    }
    setServerError(null);

    const payload = {
      amount: form.amount,
      category: form.category.trim(),
      transaction_date: form.transaction_date,
      note: form.note.trim() || null,
    };

    try {
      if (initial) {
        await updateTransaction.mutateAsync({ id: initial.id, input: payload });
      } else {
        await createTransaction.mutateAsync(payload);
      }
      onSaved();
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  }

  return (
    <Card data-testid="transaction-form">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Amount" htmlFor="amount">
            <input
              id="amount"
              type="text"
              inputMode="decimal"
              className={INPUT_CLASSES}
              value={form.amount}
              onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
              placeholder="42.50"
            />
          </FormField>
          <FormField label="Category" htmlFor="category">
            <input
              id="category"
              type="text"
              className={INPUT_CLASSES}
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              placeholder="Groceries"
            />
          </FormField>
          <FormField label="Date" htmlFor="transaction_date">
            <input
              id="transaction_date"
              type="date"
              className={INPUT_CLASSES}
              value={form.transaction_date}
              onChange={(e) => setForm((f) => ({ ...f, transaction_date: e.target.value }))}
            />
          </FormField>
          <FormField label="Note (optional)" htmlFor="note">
            <input
              id="note"
              type="text"
              className={INPUT_CLASSES}
              value={form.note}
              onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
              placeholder="What was this for?"
            />
          </FormField>
        </div>
        {(clientError || serverError) && (
          <p role="alert" className="text-sm text-rose-600">
            {clientError ?? serverError}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" data-testid="submit-transaction-form" isLoading={isSaving}>
            {initial ? "Save changes" : "Add transaction"}
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={isSaving}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function TransactionsPage() {
  const [categoryFilter, setCategoryFilter] = useState("");
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data, isLoading } = useTransactions({ category: categoryFilter || undefined });
  const deleteTransaction = useDeleteTransaction();

  const categories = useMemo(() => {
    const all = new Set<string>();
    (data?.items ?? []).forEach((t) => all.add(t.category));
    return Array.from(all).sort();
  }, [data]);

  const editingTransaction = data?.items.find((t) => t.id === editingId);

  return (
    <AppShell
      title="Transactions"
      actions={
        !isAdding &&
        !editingId && (
          <Button data-testid="add-transaction-button" onClick={() => setIsAdding(true)}>
            Add transaction
          </Button>
        )
      }
    >
      <div className="space-y-4">
        {isAdding && (
          <TransactionForm onCancel={() => setIsAdding(false)} onSaved={() => setIsAdding(false)} />
        )}
        {editingTransaction && (
          <TransactionForm
            initial={editingTransaction}
            onCancel={() => setEditingId(null)}
            onSaved={() => setEditingId(null)}
          />
        )}

        {!isAdding && !editingId && categories.length > 0 && (
          <div className="flex items-center gap-2">
            <label htmlFor="category-filter" className="text-sm font-medium text-slate-700">
              Filter by category
            </label>
            <select
              id="category-filter"
              className={`${INPUT_CLASSES} w-auto`}
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              <option value="">All categories</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </div>
        )}

        {isLoading ? (
          <Spinner label="Loading transactions" />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState
            data-testid="transactions-empty-state"
            title="No transactions yet"
            description="Add your first transaction to start tracking your spending."
            action={!isAdding ? <Button onClick={() => setIsAdding(true)}>Add transaction</Button> : undefined}
          />
        ) : (
          <Card className="overflow-hidden !p-0">
            <ul data-testid="transactions-list" className="divide-y divide-slate-100">
              {data?.items.map((transaction) => (
                <li
                  key={transaction.id}
                  data-testid={`transaction-row-${transaction.id}`}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {/* React escapes this text node automatically -- a note
                          containing "<script>...</script>" (FINTRACK-53's
                          mandatory XSS security scenario) renders as inert
                          text, never as markup. No dangerouslySetInnerHTML
                          anywhere in this file. */}
                      <span className="truncate font-medium text-slate-900">
                        {transaction.note || transaction.category}
                      </span>
                      <Badge tone="neutral">{transaction.category}</Badge>
                    </div>
                    <p className="text-sm text-slate-500">{formatDate(transaction.transaction_date)}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-semibold text-slate-900">
                      {formatCurrency(transaction.amount)}
                    </span>
                    <Button
                      variant="ghost"
                      data-testid={`edit-transaction-${transaction.id}`}
                      onClick={() => setEditingId(transaction.id)}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      data-testid={`delete-transaction-${transaction.id}`}
                      className="text-rose-600 hover:bg-rose-50"
                      onClick={() => {
                        if (window.confirm("Delete this transaction?")) {
                          deleteTransaction.mutate(transaction.id);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
