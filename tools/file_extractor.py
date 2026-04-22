"""Text extraction from file bytes — PDF, DOCX, TXT, MD.

PDF: PyMuPDF (already installed). DOCX: python-docx. TXT/MD: decode UTF-8.
Detects type from mime_type first, falls back to filename extension.

Size caps (v1): PDF max 20 pages, all files max 5MB.
"""

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# Supported MIME types and their handlers
SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}

# Fallback: filename extension → type
EXT_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".text": "txt",
    ".csv": "txt",
    ".log": "txt",
    ".json": "txt",
    ".xml": "txt",
    ".yaml": "txt",
    ".yml": "txt",
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PDF_PAGES = 20
MAX_EXTRACTED_CHARS = 10_000  # Truncate extracted text


def _detect_file_type(filename: str, mime_type: str | None) -> str | None:
    """Detect file type from MIME type or filename extension."""
    if mime_type and mime_type in SUPPORTED_MIMES:
        return SUPPORTED_MIMES[mime_type]
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return EXT_MAP.get(ext)
    return None


def _extract_pdf(file_bytes: bytes) -> str | None:
    """Extract text from PDF bytes using PyMuPDF. Caps at MAX_PDF_PAGES."""
    try:
        import pymupdf

        doc = pymupdf.open(stream=BytesIO(file_bytes), filetype="pdf")
        if doc.page_count > MAX_PDF_PAGES:
            logger.warning(f"PDF has {doc.page_count} pages, capping at {MAX_PDF_PAGES}")
        pages = min(doc.page_count, MAX_PDF_PAGES)
        text_parts = []
        for i in range(pages):
            page_text = doc[i].get_text()
            if page_text:
                text_parts.append(page_text)
        doc.close()
        return "\n".join(text_parts) if text_parts else None
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return None


def _extract_docx(file_bytes: bytes) -> str | None:
    """Extract text from DOCX bytes using python-docx."""
    try:
        from docx import Document

        doc = Document(BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs) if paragraphs else None
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return None


def _extract_text(file_bytes: bytes) -> str | None:
    """Extract text from plain text / markdown bytes."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("latin-1")
        except Exception as e:
            logger.error(f"Text decoding failed: {e}")
            return None


def extract_file_text(
    file_bytes: bytes,
    filename: str,
    mime_type: str | None = None,
) -> str | None:
    """Extract text content from file bytes.

    Args:
        file_bytes: Raw file data.
        filename: Original filename (used for type detection fallback).
        mime_type: MIME type from Telegram (preferred for type detection).

    Returns:
        Extracted text (truncated to MAX_EXTRACTED_CHARS), or None if unsupported/failed.
    """
    if not file_bytes:
        return None

    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning(f"File too large: {len(file_bytes)} bytes (max {MAX_FILE_SIZE})")
        return None

    file_type = _detect_file_type(filename, mime_type)
    if not file_type:
        logger.info(f"Unsupported file type: {filename} ({mime_type})")
        return None

    extractors = {
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "txt": _extract_text,
        "md": _extract_text,
    }
    extractor = extractors.get(file_type)
    if not extractor:
        return None

    text = extractor(file_bytes)
    if text and len(text) > MAX_EXTRACTED_CHARS:
        logger.info(f"Truncating {len(text)} chars to {MAX_EXTRACTED_CHARS}")
        text = text[:MAX_EXTRACTED_CHARS]
    return text
