# Roadmap — WeRead Archive Agent

Status date: 2026-10-14 (P2-D2 retrospective). Scope: personal-scale local automation; optional NAS and BOOK-ID-SEARCH integration.

## P0 — Runnable scaffold (this release)

- [x] One CLI for `doctor`, `login`, `upstream`, `export`, `status`.
- [x] Keep browser session local, with interactive QR login.
- [x] Adapter calls the upstream EPUB script without copying third-party source.
- [x] Built-in EPUB structural inspection and Markdown/TXT extraction, optional Calibre PDF.
- [x] Idempotent re-use of verified EPUB; source SHA and JSON receipts.
- [x] Offline unit tests with synthetic books and CI.
- [x] Real authorized two-chapter EPUB/PDF/Markdown + illustration repair acceptance, private sample QA.

## P1 — Reliability first

- [x] Implement CLI for local catalog snapshot (metadata-only); require real-book run before marking catalog count verified.
- [x] Real catalog count and chapter IDs captured: 23 entries, 22 eligible; persisted frozen chapter-order snapshot.
- [x] Chapter-level file SHA and source-to-assembled length checks, with separate structural/visual fidelity gates.
- [ ] Error taxonomies: login expiration, App-only, payment/access, throttling, parser breakage, image omissions.
- [ ] Offline snapshot of select non-private DOM/fixture patterns; test compatibility against revisions.
- [ ] Real EPUB/PDF image layout quality; RTL/vertical writing and footnote checks.

## P2 — Resumable extraction and alternatives

- [x] SQLite metadata worklist initialized from verified catalog; no data fetch on queue init.
- [x] Bounded one-chapter-per-run worker, independent EPUB checkpoints and SHA256 before COMPLETE; explicit retry of FAILED / INTERRUPTED.
- [x] Real book: 22/22 chapter coverage, ordered EPUB assembly with complete SHA and spine checks.
- [ ] Finish end-to-end resumable full-book release and catalog-to-spine QA; metadata queue alone is not sufficient.
- [ ] Canvas-based fallback adapter selected only when technically applicable.
- [ ] De-duplicate chapters and image assets, preserve stable reader and formal book IDs separately.
- [ ] Limit concurrency to one book/session; backoff on errors and respect human challenges.

### P2-C chapter assembly

- [x] Strict local-only book assembly checks eligible catalog entries, ordered queue, 22/22-or-block, verified per-chapter SHA256 and EPUB structure.
- [x] Unique image asset namespaces per chapter, per-chapter CSS, complete EPUB nav/spine, optional Markdown/PDF conversion.
- [x] Real-book EPUB/PDF/Markdown/TXT produced; 275-page PDF machine QA and representative nine-page visual audit; six owner-only Drive uploads verified by connector.
- [x] CSS 19 duplicate warnings de-duplicated to one missing background asset under an unused simple class in static XHTML; reusable offline CSS audit added.
- [x] P2-D3 bounded source-to-artifact normalized text comparison module and offline tests, with no source text in reports.
- [x] P2-D3 real source text audit: ordinals 19–21 TXT and 5/18 EPUB, 5/5 exact after documented normalization; same-upstream only.
- [x] P2-D4 provenance-gated title dedup: precisely 12 synthesized H1 removed into a separate candidate; 263-page PDF, 174/174 Markdown images and 166 PDF image objects. Original still unchanged.
- [ ] P2-D4 source-reader side-by-side final fidelity review for heading pages, TXT fallback chapters, footnotes/captions and optional CSS styles; requires user acceptance.
- [ ] Verify optional private v2 candidate upload only after local QA and human sign-off.

## P3 — More automation, less friction

- [ ] Simple local browser UI or Windows EXE, one-click install/update.
- [ ] Hermes/OpenClaw skill with job status, push notification and library file handle (not cookies).
- [ ] Optional NAS path (Tailscale/SMB), verified file transfer, local-only personal content store.
- [ ] Optional BOOK-ID-SEARCH link via metadata only; no unreviewed mutation of existing introductions.

## P4 — Research and open-source maintenance

- [x] Postmortem and status gates documented in docs/LESSONS_LEARNED_2026-10-14.md; CSS image warning semantics audited offline.

- [ ] UI regressions and anonymized reproducible bug templates.
- [x] Weekly public upstream commit check creates de-duplicated review issues, no automatic untested merges.
- [ ] Clear compatibility matrix: EPUB-format, TXT-format, canvas, illustrated, browser restricted.
- [ ] Contributor docs, changelog, tagged releases, portable binaries.

## P3-E — Reliable private delivery evidence

- [x] Cross-book real proof: two authorized books (22 and 66 eligible chapters) completed local machine QA; second private Drive release 7/7 downloaded bytes and file hashes verified.
- [x] Offline allowlisted release manifest builder and fail-closed cloud-readback verifier with synthetic regression tests on wrong folder, duplicate names, missing SHA, bytes mismatch and ACL drift.
- [ ] Build the separate authorized cloud upload/parent-reconciliation adapter, including resumable transitions and login boundaries (Issue #28).
- [ ] Human source-reader image, caption, footnote and typography sign-off before `FULL_BOOK_CONFIRMED`.

## Decision gates

- `STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` never means `FULL_TEXT_CONFIRMED`.
- Only mark full after matching catalog and sampling first/middle/last text and images.
- Existing personal credentials, books, transcripts and full text are never uploaded to GitHub CI or public Issues.