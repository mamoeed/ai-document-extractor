"""Excel (.xlsx) -> plain text for a text-only VLM message."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import openpyxl

from ..errors import FileUnreadableError

_DECIMALS = re.compile(r"0\.(0+)")
_CURRENCY_SYMBOLS = ("€", "$", "£")


def excel_to_text(path: str | Path, max_chars: int) -> tuple[str, int]:
    """Render every sheet's non-empty rows as tab-separated lines under ``## Sheet: <name>``.

    Cells are rendered as Excel displays them for percent/currency formats (``0.19`` with
    format ``0%`` becomes ``19%``) so the model sees what a human sees.
    Returns ``(text, sheet_count)``; the text is truncated at ``max_chars``.
    """
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many different types for broken files
        raise FileUnreadableError(f"Cannot open Excel file: {type(exc).__name__}: {exc}") from exc

    sections: list[str] = []
    try:
        for sheet in workbook.worksheets:
            lines = []
            for row in sheet.iter_rows():
                cells = [_format_cell(cell) for cell in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    lines.append("\t".join(cells))
            if lines:
                sections.append(f"## Sheet: {sheet.title}\n" + "\n".join(lines))
        sheet_count = len(workbook.worksheets)
    except Exception as exc:
        raise FileUnreadableError(f"Cannot read Excel file: {type(exc).__name__}: {exc}") from exc
    finally:
        workbook.close()

    text = "\n\n".join(sections)
    if not text.strip():
        raise FileUnreadableError("Excel workbook contains no data")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... truncated ...]"
    return text, sheet_count


def _format_cell(cell: Any) -> str:
    value = getattr(cell, "value", None)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return _format_number(value, str(getattr(cell, "number_format", "") or ""))
    return " ".join(str(value).split())  # tabs/newlines inside a cell -> single spaces


def _format_number(value: float, number_format: str) -> str:
    match = _DECIMALS.search(number_format)
    decimals = len(match.group(1)) if match else None
    if "%" in number_format:
        return f"{value * 100:.{decimals or 0}f}%"
    for symbol in _CURRENCY_SYMBOLS:
        if symbol in number_format:
            return f"{symbol}{value:.{2 if decimals is None else decimals}f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.12g}"  # hides float noise like 14.399999999999999
    return str(value)
