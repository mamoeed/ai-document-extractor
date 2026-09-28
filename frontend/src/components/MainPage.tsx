import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api";
import type { FileDetail, FileSummary, Health, Row } from "../types";
import { FilesTable } from "./FilesTable";
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
  const queue = useRef<{ localId: string; file: File }[]>([]);
  const running = useRef(0);
  const nextLocalId = useRef(1);

  const refresh = useCallback(async () => {
    try {
      const server = await api.listFiles();
      setRows((prev) => [...prev.filter((r) => r.local), ...server.map(toSummary)]);
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
    setRows((prev) => prev.map((r) => (r.id === id ? row : r)));
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
  }, [replaceRow, toasts, username]);

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
          <FilesTable rows={visible} selectedId={selectedId} onSelect={(row) => setSelectedId(row.id)} />
        )}
      </main>

      {selectedId && <SidePanel fileId={selectedId} onClose={() => setSelectedId(null)} onUpdated={onUpdated} />}
    </div>
  );
}
