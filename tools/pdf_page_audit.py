"""Offline PDF page-content classifier for private book QA.

Distinguish genuine no-content pages from vector-only pages. A vector-only page
is a REVIEW CANDIDATE, NOT automatically a source-proven decorative separator.
User-reviewed separator pages must be explicitly supplied per finished PDF.
No source prose, images or file identifiers appear in aggregate receipts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

PASS = "PDF_PAGE_AUDIT_PASS"
REVIEW = "PDF_PAGE_AUDIT_REVIEW_REQUIRED"


def page_kind(page) -> str:
    """Analyze page objects without requiring the PDF library at import time."""
    text = page.get_text("text")
    images = page.get_images(full=True)
    drawings = page.get_drawings()
    if text.strip():
        return "TEXT_WITH_IMAGES" if images else "TEXT"
    if images:
        return "IMAGE_ONLY"
    if drawings:
        return "VECTOR_ONLY"
    return "TRUE_BLANK"


def audit_pages(pages, *, reviewed_separator_pages=()) -> dict:
    """Read-only, one-based page numbering; never guesses vector intent."""
    approved = list(reviewed_separator_pages)
    if (any(not isinstance(p, int) or isinstance(p, bool) or p <= 0 for p in approved)
            or len(approved) != len(set(approved))):
        raise ValueError("INVALID_REVIEWED_SEPARATOR_PAGES")
    kinds = []
    for page in pages:
        kinds.append(page_kind(page))
    if not kinds:
        raise ValueError("EMPTY_PDF")
    counts = Counter(kinds)
    true_blank = [i for i, kind in enumerate(kinds, 1) if kind == "TRUE_BLANK"]
    vector = [i for i, kind in enumerate(kinds, 1) if kind == "VECTOR_ONLY"]
    if not set(approved).issubset(vector):
        raise ValueError("REVIEWED_SEPARATOR_NOT_VECTOR_ONLY")
    reviewed = sorted(approved)
    outstanding = sorted(set(vector) - set(reviewed))
    status = PASS if not true_blank and not outstanding else REVIEW
    return {
        "status": status,
        "total_pages": len(kinds),
        "page_class_counts": dict(sorted(counts.items())),
        "true_blank_pages": true_blank,
        "vector_only_pages": vector,
        "explicitly_reviewed_separator_pages": reviewed,
        "vector_only_pending_visual_review": outstanding,
        "reviewed_separators_are_manual_claims": True,
        "source_reader_visual_fidelity": "UNVERIFIED",
        "whole_book_human_signoff": "PENDING",
        "full_book_confirmed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify PDF true blanks and vector-only pages")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-separator-page", action="append", type=int, default=[],
                        help="One-based page manually checked as a separator; repeat if needed")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("PDF_AUDIT_RECEIPT_ALREADY_EXISTS")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PYMUPDF_REQUIRED_FOR_PDF_AUDIT") from exc
    with fitz.open(args.pdf) as doc:
        result = audit_pages(doc, reviewed_separator_pages=args.reviewed_separator_page)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "total_pages": result["total_pages"],
        "true_blank_pages": result["true_blank_pages"],
        "vector_only_pending_visual_review": result["vector_only_pending_visual_review"],
        "human_signoff": "PENDING",
    }, ensure_ascii=False))
    return 0 if result["status"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
