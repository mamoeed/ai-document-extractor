import { STATUS_LABELS } from "../format";
import type { Status } from "../types";

const CLASS: Record<Status, string> = {
  PROCESSING: "badge-grey",
  CONFIDENT_MATCH: "badge-green",
  LOW_CONFIDENCE: "badge-amber",
  ERROR: "badge-red",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge ${CLASS[status] ?? "badge-grey"}`}>
      {status === "PROCESSING" && <span className="spinner" aria-hidden />}
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function ReviewBadge({ corrected }: { corrected: boolean }) {
  return corrected ? (
    <span className="badge badge-purple" title="A human changed values extracted by the AI">
      ✎ Corrected by human
    </span>
  ) : (
    <span className="badge badge-blue" title="A human confirmed the AI extraction without changes">
      ✓ Confirmed by human
    </span>
  );
}
