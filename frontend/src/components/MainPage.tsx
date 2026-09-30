import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import type { FileDetail, FileSummary, Health, Row } from "../types";
import { FilesTable, isSelectable } from "./FilesTable";
import { SidePanel } from "./SidePanel";
import { ErrorDetails, useToasts } from "./Toasts";
import { UploadZone } from "./UploadZone";

const MAX_PARALLEL_UPLOADS = 3;
const POLL_MS = 5000;

function toSummary(file: FileSummary | FileDetail): Row {
  const { id, original_filename, file_type, file_sha256, uploaded_by, uploaded_at, status, match_result } = file;
  return {
    id,
    original_filename,
    file_type,
    file_sha256,
    uploaded_by,
    uploaded_at,
    status,
    match_result,
    confidence_score: file.confidence_score,
    needs_human_review: file.needs_human_review,
    human_reviewed: file.human_reviewed,
    human_corrected: file.human_corrected,
    ai_status: file.ai_status,
    ai_confidence_score: file.ai_confidence_score,
    order_number: file.order_number,
    customer_label: file.customer_label,
    customer_matched: file.customer_matched,
    items_matched: file.items_matched,
    items_total: file.items_total,
    main_issue: file.main_issue,
    issue_count: file.issue_count,
    reviewed_by: file.reviewed_by,
    reviewed_at: file.reviewed_at,
    extraction_method: file.extraction_method,
    model_name: file.model_name,
    duration_ms: file.duration_ms,
  };
}

function placeholder(localId: string, name: string, username: string): Row {
  return {
    id: localId,
    local: true,
    original_filename: name,
    file_type: null,
    file_sha256: null,
    uploaded_by: username,
    uploaded_at: new Date().toISOString(),
    status: "PROCESSING",
    match_result: null,
    confidence_score: null,
    needs_human_review: false,
    human_reviewed: false,
    human_corrected: false,
    ai_status: null,
    ai_confidence_score: null,
    order_number: null,
    customer_label: null,
    customer_matched: null,
    items_matched: null,
    items_total: null,
    main_issue: null,
    issue_count: 0,
    reviewed_by: null,
    reviewed_at: null,
    extraction_method: null,
    model_name: null,
    duration_ms: null,
  };
}

export function MainPage({ username, onLogout }: { username: string; onLogout: () => void }) {
  const toasts = useToasts();
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<ApiError | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const queue = useRef<{ localId: string; file: File }[]>([]);
  const running = useRef(0);
  const nextLocalId = useRef(1);

  const refresh = useCallback(async () => {
    try {
      const server = await api.listFiles();
      setRows((prev) => {
        const local = prev.filter((r) => r.local);
        // Uploads still in flight from this tab already have a placeholder row; hide their
        // server-side PROCESSING rows (matched by file name) so they don't show twice.
        const inFlight = new Map<string, number>();
        for (const r of local) {
          if (r.status === "PROCESSING") inFlight.set(r.original_filename, (inFlight.get(r.original_filename) ?? 0) + 1);
        }
        const serverRows = server.map(toSummary).filter((r) => {
          const pending = inFlight.get(r.original_filename) ?? 0;
          if (r.status !== "PROCESSING" || pending === 0) return true;
          inFlight.set(r.original_filename, pending - 1);
          return false;
        });
        return [...local, ...serverRows];
      });
      setListError(null);
    } catch (err) {
      setListError(err as ApiError);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    api
      .health()
      .then(setHealth)
      .catch((err) => setHealthError((err as Error).message));
  }, [refresh]);

  // Rows processing on the server but not uploaded from this tab (e.g. after a reload): poll.
  const serverProcessing = rows.some((r) => !r.local && r.status === "PROCESSING");
  useEffect(() => {
    if (!serverProcessing) return;
    const timer = window.setTimeout(() => void refresh(), POLL_MS);
    return () => window.clearTimeout(timer);
  }, [serverProcessing, rows, refresh]);

  const replaceRow = useCallback((id: string, row: Row) => {
    // Drop any other copy of the same server row (e.g. loaded by a refresh meanwhile).
    setRows((prev) => prev.filter((r) => r.id === id || r.id !== row.id).map((r) => (r.id === id ? row : r)));
  }, []);

  const pump = useCallback(() => {
    while (running.current < MAX_PARALLEL_UPLOADS && queue.current.length) {
      const job = queue.current.shift()!;
      running.current += 1;
      api
        .uploadFile(job.file)
        .then((detail) => replaceRow(job.localId, toSummary(detail)))
        .catch((err: unknown) => {
          const error = err as ApiError;
          if (error.file) {
            replaceRow(job.localId, toSummary(error.file)); // backend stored the row as ERROR
          } else if (error.status === 0 || error.status === 502 || error.status === 504) {
            // The response was lost (browser/proxy gave up), but the backend may still be working on it:
            // show the server's row instead; polling updates it when processing finishes.
            setRows((prev) => prev.filter((r) => r.id !== job.localId));
            void refresh();
            toasts.error(`No response for ${job.file.name} - it may still be processing on the server`, err);
            return;
          } else {
            replaceRow(job.localId, {
              ...placeholder(job.localId, job.file.name, username),
              status: "ERROR",
              main_issue: `Upload failed: ${error.detail ?? String(err)}`,
              issue_count: 1,
            });
          }
          toasts.error(`Processing failed: ${job.file.name}`, err);
        })
        .finally(() => {
          running.current -= 1;
          pump();
        });
    }
  }, [refresh, replaceRow, toasts, username]);

  const enqueue = useCallback(
    (files: File[]) => {
      const jobs = files.map((file) => ({ localId: `local-${nextLocalId.current++}`, file }));
      setRows((prev) => [...jobs.map((j) => placeholder(j.localId, j.file.name, username)), ...prev]);
      queue.current.push(...jobs);
      pump();
    },
    [pump, username],
  );

  const onUpdated = useCallback(
    (detail: FileDetail) => replaceRow(detail.id, toSummary(detail)),
    [replaceRow],
  );

  const deleteRow = useCallback(
    async (row: Row) => {
      const ok = window.confirm(
        `Delete "${row.original_filename}"?\n\nThis permanently removes the uploaded file and its database entry, ` +
          "including any human review. It cannot be undone.",
      );
      if (!ok) return;
      try {
        if (!row.local) await api.deleteFile(row.id); // local rows are failed uploads with no server entry
        setRows((prev) => prev.filter((r) => r.id !== row.id));
        setSelectedId((current) => (current === row.id ? null : current));
        toasts.success("Deleted", row.original_filename);
      } catch (err) {
        toasts.error(`Could not delete ${row.original_filename}`, err);
        if (err instanceof ApiError && err.status === 404) void refresh(); // already gone: resync the table
      }
    },
    [refresh, toasts],
  );

  const setChecked = useCallback((ids: string[], checked: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  // Forget selections of rows that no longer exist or can't be exported (e.g. deleted).
  useEffect(() => {
    setCheckedIds((prev) => {
      const valid = new Set(rows.filter(isSelectable).map((r) => r.id));
      const next = new Set([...prev].filter((id) => valid.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [rows]);

  async function downloadSelected() {
    const ids = rows.filter((r) => checkedIds.has(r.id)).map((r) => r.id); // table order: newest first
    setExporting(true);
    try {
      const data = await api.exportFiles(ids);
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `purchase-orders-${stamp}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      const skipped = (data.skipped as unknown[] | undefined)?.length ?? 0;
      toasts.success(
        `Downloaded ${data.count} order${data.count === 1 ? "" : "s"}`,
        skipped ? `${skipped} skipped - see "skipped" in the file` : "",
      );
    } catch (err) {
      toasts.error("Could not export the selected files", err);
    } finally {
      setExporting(false);
    }
  }

  const activeUploads = rows.filter((r) => r.local && r.status === "PROCESSING").length;
  const visible = useMemo(
    () => (needsReviewOnly ? rows.filter((r) => r.needs_human_review && r.status !== "PROCESSING") : rows),
    [rows, needsReviewOnly],
  );
  const needsReviewCount = rows.filter((r) => r.needs_human_review && r.status !== "PROCESSING").length;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          PO Extractor
          {health?.debug && (
            <span className="pill-debug" title="DEBUG=true: tracebacks are shown in error details">
              DEBUG
            </span>
          )}
        </div>
        <div className="topbar-right">
          <span className="muted">Signed in as {username}</span>
          <button className="button" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>

      <main className="content">
        {healthError && <div className="banner banner-error">Backend health check failed: {healthError}</div>}
        {health && !health.ok && (
          <div className="banner banner-error">
            <strong>Backend is not healthy.</strong>{" "}
            {Object.entries(health.details).map(([k, v]) => (
              <span key={k}>
                {k}: {v}.{" "}
              </span>
            ))}
          </div>
        )}

        <UploadZone onFiles={enqueue} active={activeUploads} />

        <div className="toolbar">
          <div className="muted">
            {rows.length} file{rows.length === 1 ? "" : "s"} · {needsReviewCount} need review
          </div>
          <div className="toolbar-right">
            {checkedIds.size > 0 && (
              <button className="link-button" onClick={() => setCheckedIds(new Set())}>
                Clear selection
              </button>
            )}
            <button
              className="button primary"
              disabled={checkedIds.size === 0 || exporting}
              onClick={() => void downloadSelected()}
              title="Download order number, customer and items of the selected files as one JSON file"
            >
              {exporting ? "Exporting…" : `Download JSON (${checkedIds.size})`}
            </button>
            <label className="checkbox">
              <input type="checkbox" checked={needsReviewOnly} onChange={(e) => setNeedsReviewOnly(e.target.checked)} />
              Needs review only
            </label>
            <button className="button" onClick={() => void refresh()}>
              Refresh
            </button>
          </div>
        </div>

        {listError && (
          <div className="error-box">
            Could not load files: {listError.detail}
            <ErrorDetails error={listError} />
          </div>
        )}
        {loading ? (
          <div className="empty">Loading…</div>
        ) : (
          <FilesTable
            rows={visible}
            selectedId={selectedId}
            onSelect={(row) => setSelectedId(row.id)}
            onDelete={(row) => void deleteRow(row)}
            selectedIds={checkedIds}
            onSetSelected={setChecked}
          />
        )}
      </main>

      {selectedId && (
        <SidePanel
          fileId={selectedId}
          onClose={() => setSelectedId(null)}
          onUpdated={onUpdated}
          onDelete={(detail) => void deleteRow(toSummary(detail))}
        />
      )}
    </div>
  );
}
