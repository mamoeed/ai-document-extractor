import zipfile

import pytest

from po_extractor import process_file
from po_extractor.errors import FileUnreadableError, UnsupportedFileTypeError
from po_extractor.extract import detect_file_type

from .conftest import (
    CUSTOMER_MASTER,
    ITEM_MASTER,
    SAMPLE_CLEARLINE_PDF,
    SAMPLE_NORTHBRIDGE_PNG,
    SAMPLE_NORTHBRIDGE_XLSX,
)


def test_detects_samples_by_content():
    assert detect_file_type(SAMPLE_CLEARLINE_PDF) == "pdf"
    assert detect_file_type(SAMPLE_NORTHBRIDGE_PNG) == "png"
    assert detect_file_type(SAMPLE_NORTHBRIDGE_XLSX) == "xlsx"


def test_content_wins_over_extension(tmp_path):
    disguised = tmp_path / "actually_png.pdf"
    disguised.write_bytes(SAMPLE_NORTHBRIDGE_PNG.read_bytes())
    assert detect_file_type(disguised) == "png"


def test_jpeg_magic(tmp_path):
    from PIL import Image

    path = tmp_path / "photo.JPG"
    Image.new("RGB", (10, 10), "white").save(path, format="JPEG")
    assert detect_file_type(path) == "jpeg"


def test_txt_is_unsupported(tmp_path):
    path = tmp_path / "order.txt"
    path.write_text("Purchase order 123")
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type(path)


def test_docx_zip_is_unsupported(tmp_path):
    path = tmp_path / "order.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<xml/>")
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type(path)


def test_pdf_extension_with_garbage_is_unreadable(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf at all")
    with pytest.raises(FileUnreadableError):
        detect_file_type(path)


def test_empty_pdf_is_unreadable(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(FileUnreadableError):
        detect_file_type(path)


# ------------------------------------------------- through process_file (no model calls)


def test_process_txt_returns_unsupported(tmp_path, settings, fake_vlm):
    fake = fake_vlm()  # no replies: any model call would fail the test
    path = tmp_path / "order.txt"
    path.write_text("hello")
    result = process_file(path, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "ERROR"
    assert result.match_result is None
    assert [i.code for i in result.issues] == ["UNSUPPORTED_FILE_TYPE"]
    assert result.meta.file_name == "order.txt"
    assert fake.calls == []


def test_process_corrupt_pdf_returns_unreadable(tmp_path, settings, fake_vlm):
    fake = fake_vlm()
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >> garbage without xref or trailer")
    result = process_file(path, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "ERROR"
    assert [i.code for i in result.issues] == ["FILE_UNREADABLE"]
    assert result.meta.file_type == "pdf"
    assert fake.calls == []


def test_process_truncated_xlsx_returns_unreadable(tmp_path, settings, fake_vlm):
    fake_vlm()
    path = tmp_path / "broken.xlsx"
    path.write_bytes(SAMPLE_NORTHBRIDGE_XLSX.read_bytes()[:500])
    result = process_file(path, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert [i.code for i in result.issues] == ["FILE_UNREADABLE"]


def test_process_missing_file_returns_unreadable(tmp_path, settings, fake_vlm):
    fake_vlm()
    result = process_file(tmp_path / "gone.pdf", CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert [i.code for i in result.issues] == ["FILE_UNREADABLE"]
