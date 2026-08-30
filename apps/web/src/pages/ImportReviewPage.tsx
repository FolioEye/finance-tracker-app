import { useRef, useState } from "react";

import { ApiError } from "../api/client";
import {
  useCommitImport,
  useDiscardImport,
  useStageImport,
  useUpdateStagedRows,
  type RowEdit,
  type StagedImport,
} from "../api/imports";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { INPUT_CLASSES } from "../components/ui/inputStyles";

const STATUS_TONE = {
  ok: "positive",
  flagged: "warning",
  invalid: "danger",
} as const;

export function ImportReviewPage() {
  const [stagedImport, setStagedImport] = useState<StagedImport | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [edits, setEdits] = useState<Record<number, RowEdit>>({});
  const [commitResult, setCommitResult] = useState<{ committed: number; skipped: number } | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  const stageImport = useStageImport();
  const updateStagedRows = useUpdateStagedRows();
  const commitImport = useCommitImport();
  const discardImport = useDiscardImport();

  async function handleFile(file: File) {
    setUploadError(null);
    setCommitResult(null);
    setEdits({});
    try {
      const result = await stageImport.mutateAsync(file);
      setStagedImport(result);
    } catch (err) {
      // FINTRACK-54 AC6: a corrupted/unparseable file must surface a
      // clear inline error, never a silent failure. The backend's actual
      // message (apps.api.domain.models.import_batch.CorruptedFileError)
      // is more specific than a generic string, so it's shown directly.
      setUploadError(err instanceof ApiError ? err.message : "Could not read this file.");
    }
  }

  function updateRowEdit(rowIndex: number, field: keyof RowEdit, value: string) {
    setEdits((prev) => ({
      ...prev,
      [rowIndex]: { ...prev[rowIndex], row_index: rowIndex, [field]: value },
    }));
  }

  async function handleSaveEdits() {
    if (!stagedImport) return;
    const edited = Object.values(edits);
    if (edited.length === 0) return;
    const result = await updateStagedRows.mutateAsync({
      importId: stagedImport.import_id,
      edits: edited,
    });
    setStagedImport(result);
    setEdits({});
  }

  async function handleCommit() {
    if (!stagedImport) return;
    const result = await commitImport.mutateAsync(stagedImport.import_id);
    setCommitResult({ committed: result.committed_count, skipped: result.skipped_count });
    setStagedImport(null);
  }

  async function handleDiscard() {
    if (!stagedImport) return;
    await discardImport.mutateAsync(stagedImport.import_id);
    setStagedImport(null);
    setEdits({});
  }

  return (
    <AppShell title="Import statement">
      <div className="space-y-4">
        {!stagedImport && (
          <Card>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void handleFile(file);
              }}
              className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors ${
                isDragging ? "border-brand-500 bg-brand-50" : "border-slate-300"
              }`}
            >
              <p className="text-sm font-medium text-slate-900">
                Drag and drop a CSV statement here
              </p>
              <p className="mt-1 text-sm text-slate-500">or</p>
              <Button
                className="mt-3"
                variant="secondary"
                isLoading={stageImport.isPending}
                onClick={() => fileInputRef.current?.click()}
              >
                Choose file
              </Button>
              <input
                ref={fileInputRef}
                data-testid="import-file-input"
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleFile(file);
                  e.target.value = "";
                }}
              />
            </div>
            {uploadError && (
              <p role="alert" data-testid="import-upload-error" className="mt-3 text-sm text-rose-600">
                {uploadError}
              </p>
            )}
          </Card>
        )}

        {commitResult && (
          <Card data-testid="import-commit-result" className="border-emerald-200 bg-emerald-50">
            <p className="text-sm font-medium text-emerald-800">
              Imported {commitResult.committed} transaction{commitResult.committed === 1 ? "" : "s"}.
              {commitResult.skipped > 0 && ` ${commitResult.skipped} row(s) were skipped.`}
            </p>
          </Card>
        )}

        {stagedImport && (
          <>
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-base font-medium text-slate-900">
                    {stagedImport.found_count} found
                  </p>
                  <p className="text-sm text-slate-500">
                    {stagedImport.flagged_count} flagged &middot; {stagedImport.invalid_count} invalid
                    &middot; {stagedImport.auto_categorised_count} of {stagedImport.found_count}{" "}
                    auto-categorised, {stagedImport.needs_review_count} need review
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    data-testid="import-discard-button"
                    onClick={handleDiscard}
                    isLoading={discardImport.isPending}
                  >
                    Discard
                  </Button>
                  {Object.keys(edits).length > 0 && (
                    <Button
                      variant="secondary"
                      onClick={handleSaveEdits}
                      isLoading={updateStagedRows.isPending}
                    >
                      Save edits
                    </Button>
                  )}
                  <Button
                    data-testid="import-commit-button"
                    onClick={handleCommit}
                    isLoading={commitImport.isPending}
                    disabled={stagedImport.found_count === 0}
                  >
                    Commit
                  </Button>
                </div>
              </div>
            </Card>

            {stagedImport.found_count === 0 ? (
              <Card data-testid="import-zero-rows">
                <p className="text-sm text-slate-500">This file had a header row but no data rows.</p>
              </Card>
            ) : (
              <Card data-testid="import-rows-table" className="overflow-x-auto !p-0">
                <table className="min-w-full divide-y divide-slate-100 text-sm">
                  <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-2">Status</th>
                      <th className="px-4 py-2">Date</th>
                      <th className="px-4 py-2">Amount</th>
                      <th className="px-4 py-2">Category</th>
                      <th className="px-4 py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {stagedImport.rows.map((row) => {
                      const edit = edits[row.row_index];
                      return (
                        <tr
                          key={row.row_index}
                          className={row.status === "invalid" ? "bg-rose-50/50" : row.status === "flagged" ? "bg-amber-50/50" : ""}
                        >
                          <td className="px-4 py-2 align-top">
                            <Badge tone={STATUS_TONE[row.status as keyof typeof STATUS_TONE] ?? "neutral"}>
                              {row.status}
                            </Badge>
                            {row.warning && <p className="mt-1 text-xs text-slate-500">{row.warning}</p>}
                          </td>
                          <td className="px-4 py-2 align-top">
                            <input
                              className={`${INPUT_CLASSES} min-w-[8rem]`}
                              value={edit?.raw_date ?? row.raw_date}
                              onChange={(e) => updateRowEdit(row.row_index, "raw_date", e.target.value)}
                            />
                          </td>
                          <td className="px-4 py-2 align-top">
                            <input
                              className={`${INPUT_CLASSES} min-w-[6rem]`}
                              value={edit?.raw_amount ?? row.raw_amount}
                              onChange={(e) => updateRowEdit(row.row_index, "raw_amount", e.target.value)}
                            />
                          </td>
                          <td className="px-4 py-2 align-top">
                            <input
                              className={`${INPUT_CLASSES} min-w-[8rem]`}
                              value={edit?.category ?? row.category}
                              onChange={(e) => updateRowEdit(row.row_index, "category", e.target.value)}
                            />
                          </td>
                          <td className="px-4 py-2 align-top">
                            <input
                              className={`${INPUT_CLASSES} min-w-[10rem]`}
                              value={edit?.note ?? row.note ?? ""}
                              onChange={(e) => updateRowEdit(row.row_index, "note", e.target.value)}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
