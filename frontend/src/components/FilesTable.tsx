import { STATUS_LABELS, dateTime, percent } from "../format";
import type { Row } from "../types";
import { ReviewBadge, StatusBadge } from "./StatusBadge";

function customerCell(row: Row) {
  if (!row.customer_label) return <span className="muted">—</span>;
  if (row.customer_matched) return row.customer_label;
  return <span className="text-warn">Not matched: {row.customer_label}</span>;
}

function itemsCell(row: Row) {
  if (row.items_total === null || row.items_total === undefined) return <span className="muted">—</span>;
  const ok = row.items_matched === row.items_total;
  return <span className={ok ? "" : "text-warn"}>{`${row.items_matched ?? 0}/${row.items_total}`}</span>;
}

export function FilesTable({
  rows,
  selectedId,
  onSelect,
  onDelete,
}: {
  rows: Row[];
  selectedId: string | null;
  onSelect: (row: Row) => void;
  onDelete: (row: Row) => void;
}) {
  if (!rows.length) {
    return <div className="empty">No files yet. Upload purchase orders above.</div>;
  }
  return (
    <div className="table-wrap">
      <table className="files-table">
        <thead>
          <tr>
            <th>File name</th>
            <th>Uploaded at</th>
            <th>Order no.</th>
            <th>Customer</th>
            <th>Items</th>
            <th>Status</th>
            <th>Confidence</th>
            <th>Main issue</th>
            <th>Human reviewed</th>
            <th aria-label="Actions"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={`${row.id === selectedId ? "selected" : ""}${row.local ? " local" : ""}`}
              onClick={() => !row.local && onSelect(row)}
              title={row.local ? "Uploading and processing…" : "Open details"}
            >
              <td className="filename">{row.original_filename}</td>
              <td className="nowrap">{dateTime(row.uploaded_at)}</td>
              <td className="nowrap">{row.order_number ?? <span className="muted">—</span>}</td>
              <td>{customerCell(row)}</td>
              <td>{itemsCell(row)}</td>
              <td className="nowrap">
                <StatusBadge status={row.status} />
                {row.human_reviewed && row.ai_status && (
                  <div className="muted small" title="Result of the AI extraction before human review">
                    AI: {STATUS_LABELS[row.ai_status]} · {percent(row.ai_confidence_score)}
                  </div>
                )}
              </td>
              <td className="nowrap">{row.status === "PROCESSING" ? "" : percent(row.confidence_score)}</td>
              <td className="issue-cell">
                {row.main_issue ?? <span className="muted">—</span>}
                {row.issue_count > 1 && <span className="more"> (+{row.issue_count - 1} more)</span>}
              </td>
              <td className="nowrap">
                {row.human_reviewed ? (
                  <>
                    <ReviewBadge corrected={row.human_corrected} />
                    <div className="muted small">
                      {row.reviewed_by} · {dateTime(row.reviewed_at)}
                    </div>
                  </>
                ) : row.needs_human_review && row.status !== "PROCESSING" ? (
                  <span className="text-warn small">Needs review</span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                {row.status !== "PROCESSING" && (
                  <button
                    className="icon-button delete-button"
                    title="Delete file and database entry"
                    aria-label={`Delete ${row.original_filename}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(row);
                    }}
                  >
                    🗑
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
