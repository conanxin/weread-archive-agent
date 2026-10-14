# WeRead Archive Agent — P2-D2 Postmortem
Date: 2026-10-14. This document contains anonymized engineering evidence, not account information, book text, chapter image bytes, or private file URLs.

## Measured state (do not overclaim)

- Catalog: 23 raw entries, 22 eligible; provider-estimated wordCount 126,332, which is **not** a count of extracted characters.
- Chapter queue: 22/22 COMPLETE, SHA-256 checked; ordinals 19–21 required explicit TXT-format recovery after EPUB-format truncation.
- Compiled EPUB: 22 ordered spine items, 158,668 extracted characters, 213 image assets, zero broken/remote XHTML image references, source-to-compiled chapter text lengths all match.
- PDF: 275 searchable pages, 137 pages with images, 166 distinct embedded image xrefs, no U+FFFD replacement characters or out-of-bounds text blocks in automated audit.
- Markdown: 174 local image references, none unresolved.
- Private delivery: six files were checked in an owner-only Drive folder, with exact size match and shared=false.
- Final human page-by-page/source comparison remains outstanding: current status is BOOK_FILES_READY_COMPLETENESS_UNVERIFIED, NOT FULL_BOOK_CONFIRMED.

## Thirteen transferable lessons

1. **Never treat a sample as the whole book.** An initial two-chapter smoke found ~250 characters because the first eligible entries were front matter. Inspect headings/length and use offset sampling into substantive chapters.
2. **Persisted login is not book access.** SESSION_SAVED only records local browser state. Require a real reader URL, catalog response and authenticated book-specific read before claiming access.
3. **Different response formats require different adapters.** At the end of the real book, EPUB-format responses held only ~10–20 characters and decorative images, while TXT-format responses returned substantial text. Preserve the EPUB sample and switch to TXT only after CONTENT_SUSPICIOUS, with a minimum text-length gate.
4. **Keep acquisition and repair separate.** Store raw chapter EPUB, image-repaired EPUB and TXT fallback independently; missing images must not force text re-download.
5. **Allowlist redirects deliberately.** One CDN origin legitimately redirected to a Tencent Cloud image host. Test image magic bytes and approve a bounded redirect family, not arbitrary third-party redirects.
6. **Annotation icons can encode prose.** The 117 repeated missing note icons carried alt annotations, some long. Preserve complete alternative text; do not truncate or pretend to reproduce original footnote typography.
7. **A warning count is not a content-loss count.** A P2-D2 offline audit of 22 source EPUBs found 19 missing CSS url() occurrences but only ONE distinct PNG reference. Every occurrence belongs to the same background-image CSS rule, and the rule's simple class is absent from the related static XHTML in all 19 chapters. This is a low-expected-impact *unused style* finding, not 19 missing illustrations. Source-reader fidelity has not been exhaustively checked.
8. **Freeze the catalog and compare order.** Require matching chapterUid and ordinal, complete SQLite states and source-file SHA-256 before EPUB merging. An EPUB that opens can still omit chapters.
9. **Use explicit state transitions.** PENDING/RUNNING/FAILED/COMPLETE, with interrupted jobs flagged, support recovery without silently retrying inaccessible content or overwriting accepted artifacts.
10. **Test Windows and Linux independently.** Python sqlite3 connection context managers manage transactions but do not close file handles. Windows temp-file deletion returned WinError 32 until tests explicitly closed connections.
11. **Machine-readable output beats terminal prose.** A Windows GBK vs UTF-8 subprocess decoding error occurred even though the requested PDF had been generated. Verify UTF-8 JSON reports and actual file size/header/hash rather than inferring success from a wrapper's exit code alone.
12. **Separate structure, layout and fidelity.** ZIP CRC, spine count, image links, searchable pages and a visual contact sheet prove different things; none alone guarantees verbatim punctuation, caption placement or authentic footnote structure.
13. **Remote delivery needs external readback.** A created Drive folder or browser toast does not prove delivery. Read returned file IDs, sizes, owner permissions and shared=false. Keep real books and login state outside the public repository.

## Required gates for future books

1. CATALOG_READY: authentic metadata only.
2. QUEUE_READY: persisted task list only.
3. CHAPTERS_FETCHED_PENDING_FULL_QA: all local chapters captured, not merged.
4. STRUCTURE_PASS_COMPLETENESS_UNVERIFIED: local file structural checks only.
5. BOOK_FILES_READY_COMPLETENESS_UNVERIFIED: finished formats with automated QA; user/source visual review still needed.
6. PRIVATE_DELIVERY_PASS: Drive verification of uploaded artifacts, independent of fidelity.
7. FULL_BOOK_CONFIRMED: use only after explicit final user acceptance and review of problematic chapters.

## Remaining work

- Review the three TXT fallback chapters and representative main-text illustrations against the source reader.
- Run the reusable offline CSS audit for future books. Missing resources under *used* or complex selectors require closer review; simple unused-class status is not source fidelity certification.
- Investigate deterministic EPUB/PDF packaging so per-build binary hashes are not confused with logical book identity.
- Keep issue #18 open until source-reader comparison is complete. Full open-source release, NAS and BOOK-ID-SEARCH integration are separate milestones.

References: merged PRs #5, #6, #8, #9, #11–#13 and #15–#17; [fidelity issue #18](https://github.com/conanxin/weread-archive-agent/issues/18).

## Addendum 2026-10-15 — Metadata, heading and newline parity

- **Don't conflate visible body text with XHTML head metadata.** MarkdownWriter previously appended `<head><title>` text. PR #22 now only writes the visible body. A replay from the privately archived EPUB reproduced the old Markdown exactly after CRLF normalization, so the fix is grounded in an observed converter behavior, not a guess.
- **Byte deltas require a newline-normalization baseline.** Original Windows Markdown was 471,465 bytes with 4,466 CRLF pairs; after CRLF→LF it was 466,999 bytes. Body-only output is 466,135 bytes; 864 normalized bytes were removed as non-body metadata, while 4,466 additional size bytes come solely from platform newline normalization. Never equate a cross-platform file-size decrease with deleted body text.
- **Headline duplication and metadata leakage are distinct faults.** In the archived EPUB, 12/22 chapters contain two consecutive identical body H1s with zero meaningful text/images in between. The source writer's additional synthetic heading is a strong hypothesis. Do not remove any original heading before comparing source chapters; see issue #23.
- **Private artifact versions should coexist.** Revised Markdown and a complete MD/TXT/174-image ZIP were uploaded privately under new names. Original EPUB/PDF and original Markdown remain unchanged so that the reproducibility evidence is not lost.
- **Offline converter replay is not live source collation.** P2-D3 same-upstream text audit still needs the authorized home PC; the desktop connector was OFFLINE. This remains BOOK_FILES_READY_COMPLETENESS_UNVERIFIED, not FULL_BOOK_CONFIRMED.
- Details: [P2-D3 offline QA](P2D3_OFFLINE_QA_2026-10-15.md).
