"""Convert WeFact attachment bytes into vision-readable images.

Images are passed through; PDFs are rendered to PNG per page (PyMuPDF).
The MCP download tool hands the resulting PNGs to Claude as Image content.
"""
from __future__ import annotations

import pymupdf

_PDF_DPI = 170
_IMAGE_SUBTYPES = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "webp": "webp", "gif": "gif"}


def attachment_to_images(data: bytes, mime: str, *, max_pages: int = 5) -> list[tuple[bytes, str]]:
    """Return a list of (image_bytes, format) for a downloaded attachment.

    - image/* → passthrough as a single item.
    - application/pdf → one PNG per page (capped at max_pages).
    - anything else → ValueError.
    """
    mime = (mime or "").split(";")[0].strip().lower()

    if mime.startswith("image/"):
        subtype = mime.split("/", 1)[1]
        return [(data, _IMAGE_SUBTYPES.get(subtype, subtype))]

    if mime == "application/pdf":
        pages: list[tuple[bytes, str]] = []
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                if len(pages) >= max_pages:
                    break
                pix = page.get_pixmap(dpi=_PDF_DPI)
                pages.append((pix.tobytes("png"), "png"))
        return pages

    raise ValueError(f"Bestandstype wordt niet ondersteund voor vision-extractie: {mime!r}")
