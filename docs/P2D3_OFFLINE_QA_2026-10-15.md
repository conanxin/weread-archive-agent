# P2-D3 Offline Artifact QA — 2026-10-15

## Scope and evidence boundary

The authorized home Windows device was **offline**, so the live chapter-source comparison introduced in PRs #20–21 did **not** run. No `SOURCE_PARITY_EXACT_FOR_CHECKED_CHAPTERS` or `FULL_BOOK_CONFIRMED` result is claimed.

Instead, the user-owned privately archived EPUB, PDF, and Markdown were read through the connected private Drive, and the conversion logic was tested offline. Only aggregate diagnostics appear here; no body text, file IDs, source reader URL, credentials, or image data is published.

## Verified measurements

| Item | Audit |
| --- | --- |
| Archived EPUB | 22 ordered chapter XHTML files, 11,222,728 bytes; contents unchanged |
| Archived PDF | 275 pages, 12,913,974 bytes; contents unchanged |
| Original Markdown | 471,465 bytes, CRLF endings (4,466 CRLF pairs) |
| Original Markdown after CRLF→LF normalization | 466,999 UTF-8 bytes |
| Reconstructed *legacy* Markdown from the same EPUB | **Exactly byte-equal** to the normalized original Markdown |
| Rebuilt body-only Markdown | 466,135 bytes with LF endings |
| Head metadata removed after normalizing newline style | 864 bytes (not 5,330 bytes) |
| Raw file size change | 5,330 bytes = 4,466 line-ending bytes + 864 XHTML head metadata bytes |
| Images in both Markdown versions | 174 identical image links in identical order; 0 newly unresolved references |
| Private revised image/Markdown/TXT ZIP | 176 entries (174 images + MD + TXT), ZIP integrity check PASS |
| Delivery | Revised Markdown and revised ZIP uploaded as **new** owner-only Drive files; original six-file delivery retained |

## Root cause: metadata leaking into text conversion

`MarkdownWriter.handle_data()` previously collected text from XHTML `<head><title>` (and could include script/style contents), even though these are not reading-body text. In the private book this produced extra pre-body title text around chapter headings.

**Fix:** PR #22 restricts conversion to `<body>`, skipping script/style/noscript text. Synthetic tests pass. The EPUB and PDF were **not** rewritten; regenerated Markdown is a separate version. The original Markdown was independently reproduced by the previous algorithm before applying the fix, reducing the chance that the observed difference arose from a mistaken reconstruction.

## Separate open issue: apparent duplicate H1 in EPUB/PDF

In the archived 22-chapter EPUB, **12 chapter ordinals** (1, 2, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18) have two consecutive body H1 headings of the same text, with no non-whitespace text or images between them.

The pinned upstream's `make_chapter_xhtml()` injects its own H1; some source XHTML bodies already contain one. This makes duplicated *synthetic* headings a strong hypothesis, but source-text and source-reader visual comparison have not yet confirmed each case. In order not to silently delete authentic material, no H1 has been stripped from EPUB/PDF. Track under issue #23.

## Two kinds of comparison must stay separate

- **EPUB → Markdown converter parity**: independently reproduced legacy output, verified the body-only delta, and checked all relative image paths. This is an offline deterministic transformation test.
- **Original source → EPUB/PDF fidelity**: requires an authorized live reread of selected chapters and visual source comparison. This is **blocked by offline home device**, not proven by matching conversion output.

## Next gates

1. Reconnect Desktop Commander and run bounded `wereadlab.py source-audit --latest --checks "19:txt,20:txt,21:txt" --live --json`. Do not run unbounded downloads.
2. Compare selected illustrated chapters plus notes and figure captions in the original reader with local PDF/EPUB.
3. Only after confirming H1 provenance, optionally generate a *new*, versioned EPUB/PDF with precise duplicate-heading removal and retest the source-parity audit's handling of inserted H1.
4. Continue keeping the existing private full-book delivery and its recorded hashes unchanged.

Status remains **BOOK_FILES_READY_COMPLETENESS_UNVERIFIED**.
