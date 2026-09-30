export type Status = "PROCESSING" | "CONFIDENT_MATCH" | "LOW_CONFIDENCE" | "ERROR";
export type Severity = "error" | "warning" | "info";

export interface Issue {
  code: string;
  severity: Severity;
  message: string;
  field?: string | null;
}

export interface FileSummary {
  id: string;
  original_filename: string;
  file_type: string | null;
  file_sha256: string | null;
  uploaded_by: string;
  uploaded_at: string;
  status: Status;
  match_result: string | null;
  confidence_score: number | null;
  needs_human_review: boolean;
  human_reviewed: boolean;
  human_corrected: boolean;
  ai_status: Status | null;
  ai_confidence_score: number | null;
  order_number: string | null;
  customer_label: string | null;
  customer_matched: boolean | null;
  items_matched: number | null;
  items_total: number | null;
  main_issue: string | null;
  issue_count: number;
  reviewed_by: string | null;
  reviewed_at: string | null;
  extraction_method: string | null;
  model_name: string | null;
  duration_ms: number | null;
}

export type Json = Record<string, unknown>;

export interface ReviewChange {
  path: string;
  before: unknown;
  after: unknown;
}

export interface MasterRecord {
  [column: string]: string | number | boolean | null;
}

export interface ProcessingResult {
  status: Status;
  match_result: string | null;
  confidence_score: number;
  needs_human_review: boolean;
  issues: Issue[];
  extracted: Json | null;
  customer_match: { matched: boolean; master_record: MasterRecord | null; candidates: MasterRecord[] };
  item_matches: {
    line_index: number;
    item_number: string | null;
    matched: boolean;
    master_record: MasterRecord | null;
    reason: string | null;
  }[];
  summary: { customer: string | null; customer_matched: boolean; items_matched: number; items_total: number };
  meta: {
    file_name: string | null;
    file_type: string | null;
    extraction_method: string | null;
    model_name: string | null;
    duration_ms: number;
    token_usage: {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      estimated_cost_usd?: number | null;
    } | null;
    llm_attempts: number;
    pages_total: number | null;
    pages_sent: number | null;
    notes: string[];
    debug: Json | null;
  };
  extraction_confidence: number | null;
  human_verified: boolean;
}

export interface FileDetail extends FileSummary {
  issues: Issue[];
  extracted_json: Json | null;
  result_json: ProcessingResult | null;
  reviewed_json: Json | null;
  reviewed_result_json: ProcessingResult | null;
  review_changes: ReviewChange[] | null;
  error_message: string | null;
}

/** A table row: a server row, or a local placeholder while its upload is in flight. */
export interface Row extends FileSummary {
  local?: boolean;
}

export interface Health {
  ok: boolean;
  db: boolean;
  master_data: boolean;
  details: Record<string, string>;
  debug: boolean;
}
