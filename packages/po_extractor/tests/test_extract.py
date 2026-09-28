import base64
import io

from PIL import Image

from po_extractor import Settings
from po_extractor.extract import build_extraction_input
from po_extractor.extract.image import load_image
from po_extractor.llm.client import build_messages

from .conftest import (
    SAMPLE_CLEARLINE_PDF,
    SAMPLE_NORTHBRIDGE_PDF,
    SAMPLE_NORTHBRIDGE_PNG,
    SAMPLE_NORTHBRIDGE_XLSX,
    SAMPLE_NORTHSTAR_XLSX,
)


def test_pdf_with_text_layer_sends_text_and_images():
    payload = build_extraction_input(SAMPLE_CLEARLINE_PDF, "pdf", Settings())
    assert payload.method == "pdf_text_vlm"
    assert payload.text.startswith("## Page 1\n")
    assert "OR2607421" in payload.text
    assert len(payload.images) == 1
    assert payload.pages_total == 1 and payload.pages_sent == 1
    assert max(payload.images[0].width, payload.images[0].height) <= 2000


def test_pdf_with_textless_page_goes_image_only():
    # Page 2 of this sample is blank (0 text chars) -> whole PDF treated as scanned.
    payload = build_extraction_input(SAMPLE_NORTHBRIDGE_PDF, "pdf", Settings())
    assert payload.method == "pdf_image_vlm"
    assert payload.text is None
    assert len(payload.images) == 2


def test_pdf_page_limit():
    payload = build_extraction_input(SAMPLE_NORTHBRIDGE_PDF, "pdf", Settings(max_pdf_pages=1))
    assert len(payload.images) == 1
    assert payload.pages_total == 2
    assert any("Only the first 1 of 2 pages" in note for note in payload.notes)


def test_pdf_threshold_is_configurable():
    payload = build_extraction_input(SAMPLE_CLEARLINE_PDF, "pdf", Settings(pdf_min_text_chars_per_page=100000))
    assert payload.method == "pdf_image_vlm"


def test_excel_to_text():
    payload = build_extraction_input(SAMPLE_NORTHBRIDGE_XLSX, "xlsx", Settings())
    assert payload.method == "excel_text_vlm"
    assert payload.images == []
    lines = payload.text.splitlines()
    assert lines[0] == "## Sheet: Purchase Order"
    assert "Pos.\tItem no.\tDescription\tQty\tUnit\tUnit price\tDiscount\tNet amount" in lines
    assert "2\t628450\tMounting kit for heating element\t5\tsets\t€18.40\t0.0%\t€92.00" in lines
    assert "\t\t\t\t\tVAT\t19%\t€229.90" in lines  # percent format rendered as displayed


def test_excel_float_noise_is_hidden():
    text = build_extraction_input(SAMPLE_NORTHSTAR_XLSX, "xlsx", Settings()).text
    assert "14.399999" not in text
    assert "€14.40" in text


def test_excel_truncation():
    payload = build_extraction_input(SAMPLE_NORTHSTAR_XLSX, "xlsx", Settings(max_text_chars=200))
    assert payload.text.endswith("[... truncated ...]")
    assert len(payload.text) < 260


def test_image_is_downscaled_and_flattened(tmp_path):
    path = tmp_path / "big.png"
    Image.new("RGBA", (4000, 1000), (0, 0, 0, 0)).save(path)
    encoded = load_image(path, max_edge_px=2000)
    assert (encoded.width, encoded.height) == (2000, 500)
    decoded = Image.open(io.BytesIO(encoded.data))
    assert decoded.mode == "RGB"
    assert decoded.getpixel((10, 10)) == (255, 255, 255)  # transparent -> white, not black


def test_small_image_kept_as_is():
    payload = build_extraction_input(SAMPLE_NORTHBRIDGE_PNG, "png", Settings())
    assert payload.method == "image_vlm"
    assert (payload.images[0].width, payload.images[0].height) == (582, 844)


def test_messages_text_only_for_excel():
    messages = build_messages(build_extraction_input(SAMPLE_NORTHBRIDGE_XLSX, "xlsx", Settings()))
    assert messages[0]["role"] == "system"
    assert "Aurora Parts" in messages[0]["content"]
    assert isinstance(messages[1]["content"], str)
    assert "PO-7642091" in messages[1]["content"]


def test_messages_image_parts():
    messages = build_messages(build_extraction_input(SAMPLE_NORTHBRIDGE_PNG, "png", Settings()))
    parts = messages[1]["content"]
    image_parts = [p for p in parts if p["type"] == "image_url"]
    assert len(image_parts) == 1
    url = image_parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))  # valid image


def test_messages_hybrid_pdf_has_images_and_text_layer():
    messages = build_messages(build_extraction_input(SAMPLE_CLEARLINE_PDF, "pdf", Settings()))
    parts = messages[1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text"]
    assert "IMAGES are authoritative" in parts[0]["text"]
    assert parts[2]["text"].startswith("### PDF text layer\n## Page 1")
