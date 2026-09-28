import type { Status } from "./types";

export const STATUS_LABELS: Record<Status, string> = {
  PROCESSING: "Processing",
  CONFIDENT_MATCH: "Confident match",
  LOW_CONFIDENCE: "Low confidence",
  ERROR: "Error",
};

export const MATCH_LABELS: Record<string, string> = {
  FULL_MATCH: "Full match",
  PARTIAL_MATCH: "Partial match",
  NO_MATCH: "No match",
};

export function percent(score: number | null | undefined): string {
  return score === null || score === undefined ? "—" : `${Math.round(score * 100)}%`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "∅";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export const EMPTY_ORDER = {
  document: { order_number: null, order_date: null, requested_delivery_date: null, currency: null },
  customer: {
    customer_number: null,
    legal_name: null,
    street: null,
    postcode: null,
    city: null,
    country: null,
    contact_name: null,
    email: null,
    phone: null,
  },
  delivery_address: { name: null, street: null, postcode: null, city: null, country: null },
  line_items: [
    {
      position: "1",
      item_number: null,
      reference_number: null,
      description: null,
      quantity: null,
      unit: null,
      unit_price: null,
      discount_percent: null,
      line_net_amount: null,
    },
  ],
  totals: { net_amount: null, vat_percent: null, vat_amount: null, gross_amount: null },
  field_confidence: { order_number: null, customer_number: null, legal_name: null, line_items: null },
  extraction_notes: null,
};

/** Postgres JSONB does not keep key order; show the order JSON in schema order for review. */
export function canonicalOrder(value: unknown, template: unknown = EMPTY_ORDER): unknown {
  if (Array.isArray(value)) {
    const itemTemplate = Array.isArray(template) ? template[0] : undefined;
    return value.map((item) => canonicalOrder(item, itemTemplate));
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const tpl =
      template && typeof template === "object" && !Array.isArray(template) ? (template as Record<string, unknown>) : {};
    const keys = [...Object.keys(tpl).filter((k) => k in obj), ...Object.keys(obj).filter((k) => !(k in tpl))];
    return Object.fromEntries(keys.map((k) => [k, canonicalOrder(obj[k], tpl[k])]));
  }
  return value;
}
