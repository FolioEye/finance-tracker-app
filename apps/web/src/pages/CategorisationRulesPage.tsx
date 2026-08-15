import { useState } from "react";

import { useCreateCategorisationRule } from "../api/categorisationRules";
import { ApiError } from "../api/client";
import { AppShell } from "../components/layout/AppShell";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { FormField } from "../components/ui/FormField";
import { INPUT_CLASSES } from "../components/ui/inputStyles";

/**
 * FINTRACK-56 scope note: the backend only exposes
 * POST /api/v1/categorisation-rules (create). There is no list, edit, or
 * delete endpoint, and no "needs review queue" endpoint distinct from the
 * existing transactions list -- see
 * apps/api/presentation/api/v1/categorisation_rules.py's own docstring
 * (ADR-012, ref'd in the Tech Lead envelope for FINTRACK-56). This page
 * is intentionally scoped down to what the API actually supports: create
 * a rule, see confirmation, done. A rules-list/edit/delete view and a
 * dedicated "needs review" queue are flagged as a backend gap rather than
 * built against endpoints that don't exist.
 */
export function CategorisationRulesPage() {
  const [merchantPattern, setMerchantPattern] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [justCreated, setJustCreated] = useState<{ merchant: string; category: string } | null>(
    null,
  );
  const createRule = useCreateCategorisationRule();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!merchantPattern.trim()) {
      setError("Merchant pattern is required.");
      return;
    }
    if (!category.trim()) {
      setError("Category is required.");
      return;
    }
    try {
      await createRule.mutateAsync({
        merchant_pattern: merchantPattern.trim(),
        category: category.trim(),
      });
      setJustCreated({ merchant: merchantPattern.trim(), category: category.trim() });
      setMerchantPattern("");
      setCategory("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  }

  return (
    <AppShell title="Categorisation rules">
      <div className="space-y-4">
        <Card>
          <p className="text-sm text-slate-500">
            Create a rule to automatically categorise future imports and transactions whose
            description matches a merchant pattern.
          </p>
          <form onSubmit={handleSubmit} className="mt-4 flex flex-wrap items-end gap-3">
            <div className="w-56">
              <FormField label="Merchant pattern" htmlFor="merchant-pattern">
                <input
                  id="merchant-pattern"
                  type="text"
                  className={INPUT_CLASSES}
                  value={merchantPattern}
                  onChange={(e) => setMerchantPattern(e.target.value)}
                  placeholder="STARBUCKS"
                />
              </FormField>
            </div>
            <div className="w-48">
              <FormField label="Category" htmlFor="rule-category">
                <input
                  id="rule-category"
                  type="text"
                  className={INPUT_CLASSES}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="Coffee & Dining"
                />
              </FormField>
            </div>
            <Button type="submit" isLoading={createRule.isPending}>
              Create rule
            </Button>
          </form>
          {error && (
            <p role="alert" className="mt-3 text-sm text-rose-600">
              {error}
            </p>
          )}
        </Card>

        {justCreated && (
          <Card className="border-emerald-200 bg-emerald-50">
            <p className="text-sm font-medium text-emerald-800">
              Future transactions matching "{justCreated.merchant}" will be categorised as{" "}
              {justCreated.category}.
            </p>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
