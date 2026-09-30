import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import { EMPTY_ORDER, MATCH_LABELS, STATUS_LABELS, canonicalOrder, dateTime, display, percent } from "../format";
import type { FileDetail, Issue, Json, ProcessingResult } from "../types";
import { JsonEditor } from "./JsonEditor";
import { ReviewBadge, StatusBadge } from "./StatusBadge";
import { ErrorDetails, useToasts } from "./Toasts";

const SEVERITY_ICON: Record<string, string> = { error: "⛔", warning: "⚠️", info: "ℹ️" };

function orderText(detail: FileDetail): string {
  return JSON.stringify(canonicalOrder(detail.reviewed_json ?? detail.extracted_json ?? EMPTY_ORDER), null, 2);
}

export function SidePanel({
  fileId,
  onClose,
  onUpdated,
  onDelete,
}: {
  fileId: string;
  onClose: () => void;
  onUpdated: (detail: FileDetail) => void;
  onDelete: (detail: FileDetail) => void;
}) {
  const toasts = useToasts();
  const [detail, setDetail] = useState<FileDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setLoadError(null);
    setEditing(false);
    setSaveError(null);
    api
      .getFile(fileId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setText(orderText(d));
      })
      .catch((err) => !cancelled && setLoadError(err as ApiError));
    return () => {
      cancelled = true;
    };
  }, [fileId]);

  const parsed = useMemo<{ value?: Json; error?: string }>(() => {
    try {
      const value = JSON.parse(text);
      if (!value || typeof value !== "object" || Array.isArray(value)) return { error: "Top level must be a JSON object" };
      return { value };
    } catch (err) {
      return { error: (err as Error).message };
    }
  }, [text]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const result: ProcessingResult | null = detail ? (detail.reviewed_result_json ?? detail.result_json) : null;
  const editable = !!detail && detail.status !== "PROCESSING" && (detail.needs_human_review || editing);
  const dirty = !!detail && text !== orderText(detail);

  async function confirm() {
    if (!detail || !parsed.value) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await api.review(detail.id, parsed.value);
      setDetail(updated);
      setText(orderText(updated));
      setEditing(false);
      onUpdated(updated);
      toasts.success(
        updated.human_corrected ? "Corrections saved" : "Details confirmed",
        `Re-validated: ${STATUS_LABELS[updated.status]} (${percent(updated.confidence_score)})`,
      );
    } catch (err) {
      setSaveError(err as ApiError);
      if (!(err instanceof ApiError && err.status === 422)) toasts.error("Could not save the review", err);
    } finally {
      setSaving(false);
    }
  }

  async function openOriginal() {
    if (!detail) return;
    const inline = detail.file_type !== "xlsx";
    const win = inline ? window.open("", "_blank") : null; // open synchronously to avoid popup blockers
    try {
      const blob = await api.originalBlob(detail.id);
      const url = URL.createObjectURL(blob);
      if (win) {
        win.location.href = url;
      } else {
        const link = document.createElement("a");
        link.href = url;
        link.download = detail.original_filename;
        link.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      win?.close();
      toasts.error("Could not open the original file", err);
    }
  }

  return (
    <>
      <div className="panel-backdrop" onClick={onClose} />
      <aside className="side-panel" aria-label="File details">
        <header className="panel-header">
          <div className="panel-title">
            <h2 title={detail?.original_filename}>{detail?.original_filename ?? "Loading…"}</h2>
            {detail && (
              <div className="panel-sub">
                <StatusBadge status={detail.status} />
                <span>Confidence {percent(detail.confidence_score)}</span>
                {detail.match_result && <span className="muted">· {MATCH_LABELS[detail.match_result]}</span>}
                {detail.human_reviewed && <ReviewBadge corrected={detail.human_corrected} />}
              </div>
            )}
          </div>
          <div className="panel-actions">
            {detail && (
              <button className="button" onClick={openOriginal}>
                {detail.file_type === "xlsx" ? "Download original" : "Open original ↗"}
              </button>
            )}
            {detail && detail.status !== "PROCESSING" && (
              <button className="button danger" onClick={() => onDelete(detail)}>
                Delete
              </button>
            )}
            <button className="icon-button big" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
        </header>

        <div className="panel-body">
          {loadError && (
            <div className="error-box">
              <strong>Could not load file:</strong> {loadError.detail}
              <ErrorDetails error={loadError} />
            </div>
          )}
          {!detail && !loadError && <div className="muted">Loading…</div>}

          {detail && (
            <>
              <ReviewHistory detail={detail} />

              {detail.error_message && (
                <section>
                  <h3>Processing error</h3>
                  <pre className="error-box traceback">{detail.error_message}</pre>
                </section>
              )}

              <section>
                <h3>Issues {detail.issues.length > 0 && <span className="count">{detail.issues.length}</span>}</h3>
                <IssueList issues={detail.issues} />
              </section>

              {result && result.extracted && <MatchSummary result={result} />}

              <section>
                <div className="section-head">
                  <h3>
                    Order JSON{" "}
                    <span className="muted small">
                      {detail.reviewed_json ? "(human-reviewed version)" : detail.extracted_json ? "(AI extraction)" : "(empty template)"}
                    </span>
                  </h3>
                  {!editable && detail.status !== "PROCESSING" && (
                    <button className="button" onClick={() => setEditing(true)}>
                      Edit
                    </button>
                  )}
                </div>
                {editable && (
                  <p className="muted small">
                    Correct any wrong values, then click <strong>Confirm correct details</strong>. Your version is saved
                    next to the AI's original extraction, which is not modified. The customer and item matching is then
                    run again on your version (no AI call), and the status, issues and confidence shown for this file
                    are replaced by that result.
                  </p>
                )}
                <JsonEditor value={text} onChange={setText} readOnly={!editable} />
                {editable && parsed.error && <div className="form-error">Invalid JSON: {parsed.error}</div>}
                {saveError && (
                  <div className="form-error">
                    {saveError.detail}
                    {saveError.errors && saveError.errors.length > 1 && (
                      <ul className="validation-errors">
                        {saveError.errors.map((e, i) => (
                          <li key={i}>
                            <code>{e.loc}</code>: {e.msg}
                          </li>
                        ))}
                      </ul>
                    )}
                    <ErrorDetails error={saveError} />
                  </div>
                )}
                {editable && (
                  <div className="editor-actions">
                    <button
                      className="button primary"
                      disabled={!!parsed.error || saving}
                      onClick={confirm}
                      title={parsed.error ? "Fix the JSON first" : "Save and re-validate"}
                    >
                      {saving ? "Saving…" : "Confirm correct details"}
                    </button>
                    <button
                      className="button"
                      disabled={!!parsed.error}
                      onClick={() => parsed.value && setText(JSON.stringify(parsed.value, null, 2))}
                    >
                      Format
                    </button>
                    {dirty && (
                      <button className="button" onClick={() => setText(orderText(detail))}>
                        Discard changes
                      </button>
                    )}
                    {editing && !detail.needs_human_review && (
                      <button
                        className="button"
                        onClick={() => {
                          setEditing(false);
                          setText(orderText(detail));
                          setSaveError(null);
                        }}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}
              </section>

              <ProcessingInfo detail={detail} />

              <section>
                <details>
                  <summary className="muted">Raw results (debug)</summary>
                  <h4>AI result (result_json)</h4>
                  <pre className="raw-json">{JSON.stringify(detail.result_json, null, 2)}</pre>
                  {detail.reviewed_result_json && (
                    <>
                      <h4>After human review (reviewed_result_json)</h4>
                      <pre className="raw-json">{JSON.stringify(detail.reviewed_result_json, null, 2)}</pre>
                    </>
                  )}
                </details>
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function ReviewHistory({ detail }: { detail: FileDetail }) {
  if (!detail.human_reviewed) {
    if (!detail.needs_human_review || detail.status === "PROCESSING") return null;
    return (
      <div className="review-box pending">
        <strong>Needs human review.</strong> Check the issues below, correct the JSON if needed and confirm.
      </div>
    );
  }
  const changes = detail.review_changes ?? [];
  return (
    <div className={`review-box ${detail.human_corrected ? "corrected" : "confirmed"}`}>
      <div className="review-flow">
        <div>
          <div className="muted small">AI extraction</div>
          {detail.ai_status && <StatusBadge status={detail.ai_status} />} {percent(detail.ai_confidence_score)}
        </div>
        <div className="arrow">→</div>
        <div>
          <div className="muted small">
            {detail.human_corrected ? "Corrected" : "Confirmed"} by {detail.reviewed_by} · {dateTime(detail.reviewed_at)}
          </div>
          <StatusBadge status={detail.status} /> {percent(detail.confidence_score)}
        </div>
      </div>
      {changes.length > 0 ? (
        <table className="changes">
          <thead>
            <tr>
              <th>Field</th>
              <th>AI value</th>
              <th>Human value</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => (
              <tr key={c.path}>
                <td>
                  <code>{c.path}</code>
                </td>
                <td className="before">{display(c.before)}</td>
                <td className="after">{display(c.after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="small">The reviewer confirmed the AI values without changes.</div>
      )}
    </div>
  );
}

function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <div className="ok-text">No issues ✓</div>;
  return (
    <ul className="issues">
      {issues.map((issue, i) => (
        <li key={i} className={`issue issue-${issue.severity}`}>
          <span className="issue-icon" aria-label={issue.severity}>
            {SEVERITY_ICON[issue.severity] ?? "•"}
          </span>
          <div>
            <div>{issue.message}</div>
            <div className="muted small">
              <code>{issue.code}</code>
              {issue.field && (
                <>
                  {" "}
                  · <code>{issue.field}</code>
                </>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

const CUSTOMER_FIELDS = ["Customer no.", "Legal name", "Street", "Postcode", "City", "Country", "Active"];

function MatchSummary({ result }: { result: ProcessingResult }) {
  const lines = ((result.extracted?.line_items as Json[] | undefined) ?? []) as Record<string, unknown>[];
  const { customer_match: customer } = result;
  return (
    <section>
      <h3>Match summary</h3>
      <div className="match-block">
        <div className="match-title">
          {customer.matched ? <span className="ok-text">✓</span> : <span className="bad-text">✗</span>} Customer
        </div>
        {customer.matched && customer.master_record ? (
          <dl className="kv">
            {CUSTOMER_FIELDS.map((key) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{display(customer.master_record?.[key])}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <div className="small">
            Not found in customer master{result.summary.customer ? `: ${result.summary.customer}` : ""}.
            {customer.candidates.length > 0 && (
              <div className="muted">
                Master candidates:{" "}
                {customer.candidates.map((c) => `${c["Legal name"]} (${c["Customer no."]})`).join(", ")}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="match-block">
        <div className="match-title">
          Items {result.summary.items_matched}/{result.summary.items_total}
        </div>
        <table className="items-table">
          <thead>
            <tr>
              <th></th>
              <th>#</th>
              <th>Item no.</th>
              <th>Document</th>
              <th>Qty</th>
              <th>Master item</th>
            </tr>
          </thead>
          <tbody>
            {result.item_matches.map((m) => {
              const line = lines[m.line_index] ?? {};
              return (
                <tr key={m.line_index}>
                  <td>{m.matched ? <span className="ok-text">✓</span> : <span className="bad-text">✗</span>}</td>
                  <td>{display(line.position ?? m.line_index + 1)}</td>
                  <td>
                    <code>{m.item_number ?? "∅"}</code>
                    {line.reference_number ? <div className="muted small">ref: {String(line.reference_number)}</div> : null}
                  </td>
                  <td className="small">{display(line.description)}</td>
                  <td className="nowrap small">
                    {display(line.quantity)} {line.unit ? String(line.unit) : ""}
                  </td>
                  <td className="small">
                    {m.master_record ? (
                      <>
                        {display(m.master_record["Description"])}
                        <div className="muted">
                          {display(m.master_record["Base UoM"])} · €{display(m.master_record["Net price EUR"])}
                          {m.master_record["Active"] !== "Yes" && " · inactive"}
                        </div>
                      </>
                    ) : (
                      <span className="bad-text">{m.reason === "ITEM_INACTIVE" ? "Inactive" : "Not found"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProcessingInfo({ detail }: { detail: FileDetail }) {
  const meta = detail.result_json?.meta;
  const rows: [string, string][] = [
    ["Uploaded", `${dateTime(detail.uploaded_at)} by ${detail.uploaded_by}`],
    ["File type", detail.file_type ?? "—"],
    ["Extraction method", detail.extraction_method ?? "—"],
    ["Model", detail.model_name ?? "—"],
    ["Duration", detail.duration_ms != null ? `${(detail.duration_ms / 1000).toFixed(1)} s` : "—"],
  ];
  if (meta?.token_usage) {
    rows.push([
      "Tokens",
      `${meta.token_usage.prompt_tokens} in / ${meta.token_usage.completion_tokens} out` +
        (meta.llm_attempts > 1 ? ` (${meta.llm_attempts} attempts)` : ""),
    ]);
    const cost = meta.token_usage.estimated_cost_usd;
    rows.push(["Cost (DeepInfra estimate)", cost != null ? `$${cost.toFixed(5)}` : "not reported"]);
  }
  if (meta?.pages_total) rows.push(["Pages", `${meta.pages_sent ?? "?"} of ${meta.pages_total} sent as images`]);
  if (detail.result_json?.extraction_confidence != null) {
    rows.push(["AI field confidence (min)", percent(detail.result_json.extraction_confidence)]);
  }
  rows.push(["SHA-256", detail.file_sha256 ?? "—"]);
  return (
    <section>
      <h3>Processing</h3>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className={k === "SHA-256" ? "mono small" : ""}>{v}</dd>
          </div>
        ))}
      </dl>
      {meta?.notes && meta.notes.length > 0 && (
        <ul className="notes small muted">
          {meta.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {typeof detail.result_json?.extracted?.extraction_notes === "string" && (
        <div className="small">
          <strong>Model notes:</strong> {String(detail.result_json.extracted.extraction_notes)}
        </div>
      )}
      {meta?.debug && <pre className="raw-json">{JSON.stringify(meta.debug, null, 2)}</pre>}
    </section>
  );
}
