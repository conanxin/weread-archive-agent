# Research log

## 2026-10-13 — Foundation

### Sources

1. `finlater/weread.koplugin` (https://github.com/finlater/weread.koplugin) — AGPL-3.0; includes `scripts/fetch_weread_epub.py` with `--reader-url`, `--cookie-file`, `--save-cookies`, `--output`, `--limit`, `--skip`. Its developer's docs record a full 134-chapter, 282-image EPUB trial and acknowledge format-specific limitations. Source: https://github.com/finlater/weread.koplugin/blob/main/docs/weread-content-research.md
2. `lbq110/weread-exporter` (https://github.com/lbq110/weread-exporter) — Playwright Canvas fillText and viewport image capture, Markdown oriented. Declares App-only books unsupported; text/image ordering caveats. Its repository did not expose a clear LICENSE file at the time of review: do not vendor/relicense without checking.
3. `teng-lin/weread-omni` (https://github.com/teng-lin/weread-omni) — user-library / notes / metadata agent-oriented CLI, not a drop-in full-book content engine.
4. `drunkdream/weread-exporter` (https://github.com/drunkdream/weread-exporter/issues/127) — reported 404 on specific books, May 2026. See https://github.com/drunkdream/weread-exporter/issues/106 for earlier automation warning report.

### Decisions

- Create an independent local orchestration layer; reference upstream via Git URL and subprocess invocation rather than copying AGPL code.
- Support authenticated, readable content only; no bypass of app-only restrictions/captchas/access controls.
- Treat file structural validity, catalog coverage, and true textual completeness as separate gates.
- No real account was accessed during P0. Local Windows device has been observed online with Python 3.12/3.13, Git, GitHub CLI and Calibre; Pandoc not installed, hence built-in Markdown conversion.

### Unknowns / real-world gates

- Login cookie jar compatibility across reader sessions; cookie renewal behavior.
- Which book formats can be extracted via source API after October 2026 changes.
- Image order, footnotes, tables, section boundaries, and authenticity of chapter coverage on a real book.

## 2026-10-13 — Real-book sample and image repair hypothesis

- First sample fetched front matter (2 sections, 250 characters); later 2-chapter offset sample fetched substantial actual body text: **21,945 characters** total (9,691 + 12,254), EPUB structure otherwise valid. **Not a verified full-book export.**
- Image audit of the two body sections found **150 total references**: 117 occurrences of one missing `Images/note.png` marker plus 33 distinct `res.weread.qq.com/wrepub/` CDN resources. Only three other images were packaged by upstream TAR-based asset handler. The prior `STRUCTURE_INCOMPLETE` accurately prevented incomplete files being marked ready.
- Root cause hypothesis: upstream resource rewriting covers TAR-sourced chapter assets but not these external CDN images and the shared missing note icon.
- P1 repair feature: fix already downloaded `*.partial.epub` rather than requesting full text again. Download allowlisted CDN images, dedupe, update OPF; preserve missing note icon semantics via visible text marker; do not claim image or catalog completeness if unresolved. See GitHub issue #7.
- Verify on the user's computer after synthetic CI passes. **Do not commit book URL, chapter text, credentials or image files.**


## 2026-10-13 — P1 real image repair verified on Windows

- A real authenticated two-body-chapter EPUB was preserved as `*.partial.epub` and repaired **without re-fetching chapter text**. The original 21,945 characters of chapter-body extraction remain the provenance baseline; later EPUB validators count additional visible annotation text.
- The original sample had 117 missing references to `Images/note.png` (all carrying `alt` annotations of 19–238 characters) and 33 different `https://res.weread.qq.com/` remote image URLs. Initial strict host policy rejected all images because WeRead redirects to Tencent's `*.gfp.tencent-cloud.com` CDN; a one-image local HTTP test verified HTTPS 200, JPEG content. Fix was to allow only that trusted redirect family and preserve full `alt` note text.
- Real repaired EPUB: `IMAGES_REPAIRED` / `STRUCTURE_PASS_COMPLETENESS_UNVERIFIED`, **33/33** remote images embedded, **117** annotated note markers converted, **36** EPUB manifest image assets, zero missing/remote references. Markdown exists (33 local image assets), and Calibre generated a PDF.
- PDF inspection: **47 pages**, **33 uniquely embedded images**, images on 26 pages, text extractable on all 47 pages (30,012 extracted characters). This establishes a working two-chapter EPUB → Markdown/PDF pipeline, **not** a complete, visually audited book.
- Implemented in [PR #8](https://github.com/conanxin/weread-archive-agent/pull/8) and [PR #9](https://github.com/conanxin/weread-archive-agent/pull/9); offline test suite **13/13 PASS** on the Windows machine. See image repair [Issue #7](https://github.com/conanxin/weread-archive-agent/issues/7).
- Pending: visual rendering QA for footnotes, figure captions and figure/paragraph ordering; compare catalog vs full-book chapter coverage. Long-book checkpoint/resume is still not implemented.

## 2026-10-14 — P2-A authenticated catalog + P2-B1 SQLite queue acceptance

- On the authorized local Windows machine, a real book catalog scan returned **23 raw entries**, **22 selected-for-export chapters**, one excluded cover, **126,332 provider wordCount** total for eligible chapters, and zero duplicate chapter UIDs. This is a metadata-only estimate, **not captured full-text bytes**. Private `catalog.json` and `catalog.report.json` are under `.local/library/<reader-id>/`.
- [PR #11](https://github.com/conanxin/weread-archive-agent/pull/11) adds `wereadlab.py catalog ... --json` with a separate authenticated reader/catalog request and an explicit `CATALOG_READY` gate; local Windows 18/18 fixture tests passed.
- [PR #12](https://github.com/conanxin/weread-archive-agent/pull/12) adds `queue init --latest --json` and `queue status --latest --json`. The real private SQLite queue was initialized and queried successfully: **22 PENDING, 0 RUNNING, 0 FAILED, 0 COMPLETE**. Queue order / chapter IDs match the catalog snapshot. This is only a worklist, not a capture/resume engine.
- Real Windows regression found a platform-specific fixture problem that Linux CI missed: Python's `with sqlite3.connect(...)` manages transactions but **does not close the connection**. Windows then refuses to unlink the temporary SQLite file (`WinError 32`). [PR #13](https://github.com/conanxin/weread-archive-agent/pull/13) explicitly closes fixtures; Windows 22/22 fixture tests passed.
- The next required development gate is P2-B2: single-chapter worker that stores validated artifacts and SHA256 before atomically marking a queue row COMPLETE, can resume PENDING/FAILED only, retains prior chapter data on image-repair failure, and stops on authentication/access challenges. Only after all 22 entries are checked against the EPUB spine and QA passes can the full-book deliverable be described as complete.
- Detailed project recap and lessons live in the private Notion page created on 2026-10-14; never copy account cookies or private book contents into public GitHub.

## 2026-10-14 — Book tail format mismatch: EPUB image shells, TXT full text

- Real worklist of 22 selected entries reached 18 COMPLETE. Ordinals **19** and **20** failed `CONTENT_SUSPICIOUS`: provider estimated 2,060 and 1,918 words respectively; EPUB branch had only about a dozen extracted text characters and mostly white/strip PNG decorations. **Correct fail-closed behavior**; HTML/image structure is not enough to assert text completeness.
- One-shot alternate per-chapter `t_0/t_1` TXT fetches on the same authenticated book returned substantial text: 19 → 2,069 characters, 20 → 2,117; subsequent checks showed 21 → 9,659, 22 → 1,548. No chapter text/URLs/cookies printed or committed; figures are local diagnostics. These values support adding a TXT recovery adapter for the tail instead of weakening validation.
- New P2-B3: If the EPUB text is under the severe-truncation threshold for 500+ provider-word chapters, try TXT once and require at least 60% of provider wordCount. Save a distinct `NNNN.txt-fallback.partial.epub` and retain original image-oriented EPUB checkpoints; report `txt_fallback_ordinals` and require extra visual QA. Failed fallback leaves chapter FAILED, no silent substitution.
- P2-C assembler must match every frozen catalog entry to EPUB spine and SHA256 before full-book release; unresolved CSS decoration URLs are reported, not allowed as invisible breaks. This book was **not** yet fully merged or delivered at this diagnostic point.
