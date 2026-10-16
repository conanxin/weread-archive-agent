# P3-F | Source-reader visual-fidelity acceptance gate

## Purpose
A complete chapter queue, valid EPUB, searchable PDF and owner-only private
cloud receipt do **not** establish page-by-page visual fidelity. Distinguish
machine-readable structure from original-reader presentation and human sign-off.

## Representative visual checklist
1. Review the front matter: copyright title, author photo, its caption and preface.
2. Inspect **every PDF page containing an embedded image**, not just random pages.
   Track image occurrence count separately from unique embedded image hashes.
3. Compare at least one chapter opener, a mid-book footnote/annotation, and the
   final afterword to the same authorized source-reader location.
4. Confirm caption text is readable, notes remain intelligible, headings occur
   once, and no illustration is missing/cropped; record page-level evidence.
5. Record explicit human decision: ACCEPT / REJECT / NEEDS_REVIEW.
   If unavailable, remain HUMAN_VISUAL_FIDELITY_PENDING.

## P3-F corner case: wrapped copyright heading
Some source EPUB front matter contains an original named copyright title H1
inside `<div class="newCopyRightTitleWrapper">`, immediately after an extra
plain H1 injected by the pinned exporter. The earlier adjacent-H1 matcher only
catches two directly adjacent H1 elements; it misses this wrapped variant.

The heading tool now recognizes **only** this exact wrapper, the expected source
title class, and a generated plain H1 when all three visible title strings match
the frozen catalog title. Any intervening paragraph, different title or wrapper
class fails closed. Preserve all source styling, copyright text and other EPUB
entries; modify only the proven generated H1.

## Safe versioned output
```powershell
python -m tools.heading_fidelity --book-dir ".local/library/<book-id>" --output-version v3-headings
python -m tools.heading_fidelity --book-dir ".local/library/<book-id>" --output-version v3-headings --build-versioned
```
Use v3 output **only if the audit identifies the exact problem** and the frozen
source/queue hashes pass. Never overwrite the original or previously delivered v2.
Re-check EPUB spine, image refs, copied ZIP members, PDF rendering and front-matter
appearance. Build and ship PDF only as an explicitly labeled candidate.

## Status model
- `PRIVATE_DELIVERY_PASS`: verified private cloud bytes and permission.
- `P3F_PDF_VISUAL_SAMPLE_PASS`: inspected PDF render and representative pages.
- `SOURCE_READER_VISUAL_PARITY_PENDING`: no paired original-reader inspection.
- `HUMAN_VISUAL_FIDELITY_PENDING`: final reader has not signed off.
- `FULL_BOOK_CONFIRMED`: **never** inferred from any earlier technical gate.

No book text, screenshots, cookies, private reader IDs, account credentials or
private Drive URLs belong in this public document.
