# Roadmap — WeRead Archive Agent

Status date: 2026-10-13. Scope: personal-scale local automation; optional NAS and BOOK-ID-SEARCH integration.

## P0 — Runnable scaffold (this release)

- [x] One CLI for `doctor`, `login`, `upstream`, `export`, `status`.
- [x] Keep browser session local, with interactive QR login.
- [x] Adapter calls the upstream EPUB script without copying third-party source.
- [x] Built-in EPUB structural inspection and Markdown/TXT extraction, optional Calibre PDF.
- [x] Idempotent re-use of verified EPUB; source SHA and JSON receipts.
- [x] Offline unit tests with synthetic books and CI.
- [ ] Live account / 2-chapter export acceptance test (needs interactive QR login and readable book).

## P1 — Reliability first

- [x] Implement CLI for local catalog snapshot (metadata-only); require real-book run before marking catalog count verified.
- [ ] Capture real catalog count, chapter IDs and per-chapter word counts before extraction.
- [ ] Chapter-level SHA and evidence; distinguish visual completeness from mere structural completeness.
- [ ] Error taxonomies: login expiration, App-only, payment/access, throttling, parser breakage, image omissions.
- [ ] Offline snapshot of select non-private DOM/fixture patterns; test compatibility against revisions.
- [ ] Real EPUB/PDF image layout quality; RTL/vertical writing and footnote checks.

## P2 — Resumable extraction and alternatives

- [x] SQLite metadata worklist initialized from verified catalog; no data fetch on queue init.
- [ ] Per-chapter checkpoint and persistent job queue (SQLite); interrupted jobs resume from failed chapter.
- [ ] Canvas-based fallback adapter selected only when technically applicable.
- [ ] De-duplicate chapters and image assets, preserve stable reader and formal book IDs separately.
- [ ] Limit concurrency to one book/session; backoff on errors and respect human challenges.

## P3 — More automation, less friction

- [ ] Simple local browser UI or Windows EXE, one-click install/update.
- [ ] Hermes/OpenClaw skill with job status, push notification and library file handle (not cookies).
- [ ] Optional NAS path (Tailscale/SMB), verified file transfer, local-only personal content store.
- [ ] Optional BOOK-ID-SEARCH link via metadata only; no unreviewed mutation of existing introductions.

## P4 — Research and open-source maintenance

- [ ] UI regressions and anonymized reproducible bug templates.
- [x] Weekly public upstream commit check creates de-duplicated review issues, no automatic untested merges.
- [ ] Clear compatibility matrix: EPUB-format, TXT-format, canvas, illustrated, browser restricted.
- [ ] Contributor docs, changelog, tagged releases, portable binaries.

## Decision gates

- `STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` never means `FULL_TEXT_CONFIRMED`.
- Only mark full after matching catalog and sampling first/middle/last text and images.
- Existing personal credentials, books, transcripts and full text are never uploaded to GitHub CI or public Issues.