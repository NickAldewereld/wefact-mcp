"""Tests for attachment → vision-image conversion."""
from __future__ import annotations

import pymupdf
import pytest

from wefact_mcp.attachments import attachment_to_images


def _one_page_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Bon: EUR 12,34")
    return doc.tobytes()


def test_pdf_renders_to_png_pages() -> None:
    images = attachment_to_images(_one_page_pdf(), "application/pdf")
    assert len(images) >= 1
    data, fmt = images[0]
    assert fmt == "png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_image_is_passed_through() -> None:
    fake_png = b"\x89PNG\r\n\x1a\n" + b"rest"
    images = attachment_to_images(fake_png, "image/png")
    assert images == [(fake_png, "png")]


def test_jpeg_passthrough_format() -> None:
    images = attachment_to_images(b"\xff\xd8\xff", "image/jpeg")
    assert images[0][1] in ("jpeg", "jpg")


def test_unknown_mime_raises() -> None:
    with pytest.raises(ValueError, match="ondersteun"):
        attachment_to_images(b"data", "application/zip")


def test_pdf_respects_max_pages() -> None:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    images = attachment_to_images(doc.tobytes(), "application/pdf", max_pages=2)
    assert len(images) == 2
