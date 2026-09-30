"""Prompts for the extraction call (§3.4). The model only extracts; it never judges matches."""

from __future__ import annotations

from typing import Optional

# Kept as valid JSON so a test can check it stays in sync with schemas.ExtractedOrder.
SCHEMA_TEMPLATE = """{
  "document": {
    "order_number": "string, REQUIRED - the PO number (labels like 'Order number', 'Purchase order no.', 'PO no.', 'Order reference')",
    "order_date": "YYYY-MM-DD or null",
    "requested_delivery_date": "YYYY-MM-DD or null",
    "currency": "ISO 4217 code such as EUR, or null"
  },
  "customer": {
    "customer_number": "string, REQUIRED - value labelled 'Customer no.' / 'Customer number' / 'Our customer no.' (NEVER 'Supplier number')",
    "legal_name": "string, REQUIRED - full legal name of the company ISSUING the PO, with legal form (GmbH, Ltd., ...)",
    "street": "string or null",
    "postcode": "string or null",
    "city": "string or null",
    "country": "string or null",
    "contact_name": "string or null",
    "email": "string or null",
    "phone": "string or null"
  },
  "delivery_address": {
    "name": "string or null",
    "street": "string or null",
    "postcode": "string or null",
    "city": "string or null",
    "country": "string or null"
  },
  "line_items": [
    {
      "position": "string or null - line/position number as printed, e.g. '001' or '1'",
      "item_number": "string, REQUIRED - the value labelled 'Item no.' for this line (main column, or inline like 'Item no.: X'); never an unlabelled number",
      "reference_number": "string or null - any other per-line number ('Your item no.', 'Your Order no.', 'Drawing no.', an unlabelled manufacturer/part no.)",
      "description": "string or null",
      "quantity": "number or null",
      "unit": "string or null - exactly as printed, e.g. 'Stk', 'pcs', 'canisters'",
      "unit_price": "number or null - price per 1 unit",
      "discount_percent": "number or null",
      "line_net_amount": "number or null"
    }
  ],
  "totals": {
    "net_amount": "number or null",
    "vat_percent": "number or null - e.g. 19 for 19 %",
    "vat_amount": "number or null",
    "gross_amount": "number or null"
  },
  "field_confidence": {
    "order_number": "number 0..1",
    "customer_number": "number 0..1",
    "legal_name": "number 0..1",
    "line_items": "number 0..1 - the LOWEST confidence across all item_number and quantity values"
  },
  "extraction_notes": "string or null - anything you found unclear"
}"""

SYSTEM_PROMPT = f"""You extract purchase orders (POs) into JSON for the supplier Aurora Parts.

## Who is who
- WE are the supplier, Aurora Parts (printed e.g. as "Aurora Parts Deutschland GmbH" or "Aurora Parts Germany GmbH"). The PO is addressed TO us. The recipient address block is us - NEVER use it as the customer.
- The CUSTOMER is the company that ISSUED the PO. Identify it from the letterhead, logo, footer, or the small sender line printed above the recipient address.
- customer.legal_name: the issuer's full legal company name including its legal form (GmbH, Ltd., AG, ...), usually printed in the footer or the sender line. Prefer that over a logo or brand name. Never use a department, project or site name.
- customer.customer_number: the value labelled "Customer no.", "Customer number" or "Our customer no.". NEVER use "Supplier number" / "Supplier no." / "Vendor no." - that is our number at the customer.
- customer street/postcode/city/country: the issuer's own address (letterhead, footer or sender line; the billing address only if nothing else is printed). contact_name/email/phone: the issuer's contact for this order.
- delivery_address: the block labelled "Delivery address", "Ship to" or "Deliver to". All null if there is none.

## Line items
- One entry per ordered position. No entries for subtotals, VAT, totals, notes or text-only lines.
- item_number: the value labelled "Item no." for that line - in the main "Item no." column, or printed inline next to the label (e.g. "Item no.: AB-12345"). A number printed with the description but WITHOUT the "Item no." label (e.g. a manufacturer or part number) is never the item_number, even if it appears first.
- reference_number: any other per-line number such as "Your item no.", "Your Order no.", "Drawing no." or an unlabelled manufacturer/part number. If there are several, join them with "; " in printed order, the customer's own item/order number first.
- description: as printed (join multi-line descriptions with a space).
- quantity and unit as printed; unit_price is the price per 1 unit; line_net_amount is the line's net total.

## Formats
- Numbers are JSON numbers with a dot as decimal separator and no thousands separators. Convert German formats: "1.118,00" -> 1118.00, "5,00" -> 5, "2.250,00" -> 2250.00.
- Percentages are plain numbers in percent: "19 %" -> 19.
- Dates are ISO "YYYY-MM-DD": "18.08.2026" -> "2026-08-18". requested_delivery_date is the requested/latest delivery date of the order; if only per-line delivery dates exist and they are all equal, use that date.
- IDs (order number, customer number, item numbers, postcodes) are strings copied character by character.

## Rules
- Copy values exactly as printed. Do not invent, complete, translate or correct anything. Use null when a value is not present.
- Never put a value into a field whose label does not fit, just to fill it.
- field_confidence: for each key, a number 0..1 for how sure you are that the value is correct AND taken from the right label: 1.0 = clearly printed and unambiguous; 0.8 = readable but label or position slightly ambiguous; 0.5 = hard to read or inferred; 0 = not found. Be honest - low values send the order to a human reviewer.
- extraction_notes: short notes on anything unclear (hard-to-read characters, ambiguous labels, several candidate values), or null.
- Respond with ONLY the JSON object, minified on a single line (no indentation, no line breaks) - no markdown, no code fences, no comments.

## JSON schema (types and meaning of every field)
{SCHEMA_TEMPLATE}
"""

_PDF_TEXT_AND_IMAGES = """Extract the purchase order from this PDF ({pages_total} page(s)).
The rendered page images are attached (first {pages_sent} page(s)). Below them is the PDF's embedded text layer.
The IMAGES are authoritative: the text layer may come from OCR and can contain character errors (e.g. "rn" instead of "ch", "l" instead of "I") and a scrambled reading order that separates table columns from their rows. Use the text layer only to double-check digits and spellings that are hard to read in the images."""

_PDF_IMAGES = """Extract the purchase order from this scanned PDF ({pages_total} page(s)). The page images are attached in page order (first {pages_sent} page(s))."""

_IMAGE = """Extract the purchase order from the attached image."""

_EXCEL = """Extract the purchase order from this Excel workbook.
Each sheet starts with "## Sheet: <name>". Each line is one non-empty row; cells are separated by TAB characters and empty cells are kept as empty fields, so columns stay aligned with their header row."""

CLOSING_INSTRUCTION = "Return only the JSON object."


def build_user_instruction(method: str, *, pages_total: Optional[int] = None, pages_sent: Optional[int] = None) -> str:
    templates = {
        "pdf_text_vlm": _PDF_TEXT_AND_IMAGES,
        "pdf_image_vlm": _PDF_IMAGES,
        "image_vlm": _IMAGE,
        "excel_text_vlm": _EXCEL,
    }
    return templates[method].format(pages_total=pages_total, pages_sent=pages_sent)


def build_retry_message(error: str) -> str:
    return (
        "Your previous response could not be used:\n"
        f"{error}\n\n"
        "Fix the problem and respond again with ONLY the complete, corrected JSON object matching the schema."
    )

