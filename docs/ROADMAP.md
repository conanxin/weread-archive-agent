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

## P4-A｜双书复盘与第三本迁移｜2026-10-17

- [x] 对第一本 22 章与第二本 66 章的来源、标题、注释、图片、PDF、私有交付失败模式做通用复盘，见 `docs/CROSS_BOOK_THIRD_BOOK_PLAYBOOK.md`。
- [x] 修正 AGENTS.md 中过时且矛盾的 queue init/run 指令；新书全部队列操作明确指向返回的 book-specific catalog/SQLite，而非误选 `--latest`。
- [x] Windows 本地工具 doctor 实际返回 READY，两个已存在的书籍 catalog 可以读取；私人第三本任务状态保留 `G0_TARGET_REQUIRED`，未抓取正文。
- [ ] 收到第三本经授权的真实 reader URL，完成独立 catalog 和含实质正文的章节 pilot；**当前没有给定第三本，禁止猜 ID 或虚报正在导出**。
- [ ] pilot 通过后才按 bounded queue 和每章 SHA 采集、合并、来源/视觉 QA、owner-only Drive 全量 SHA 回读，交付再与人工阅读签收分开。

## P4-E｜三本导书复盘与第四本复用准备｜2026-10-17

- [x] 第三本 602/602 个条目完成有界采集、11 章路线图与后记共12处独立图文融合；来源缓存正文 602/602、引用图片37/37、资源86/86、PDF814页602书签、私有Drive 9/9 完整云端 SHA 回读。
- [x] 归纳 22/66/602 三种不同目录结构与典型问题，更新新书执行契约和跨书经验文档 `docs/P4E_THREE_BOOK_POSTMORTEM_AND_NEXT_BOOK.md`。
- [x] 新增只读 preassembly_risk_audit：识别可疑短章、未引用的大幅路线图及重复图片，不因 zip 完整就认定视觉完整；纯合成用例覆盖。
- [ ] 用户指定第四本真实微信读书阅读页，取得独立目录、前中后小样与新书章队列。在此之前不推断 reader ID、不要复用前三本路径。
- [ ] 下一本遵循有界续传、离线图文及注释QA、固定 A4 PDF、真实 owner-only Drive 父目录+完整 SHA 回读；整书人工阅读签收独立。

## Decision gates

- `STRUCTURE_PASS_COMPLETENESS_UNVERIFIED` never means `FULL_TEXT_CONFIRMED`.
- Only mark full after matching catalog and sampling first/middle/last text and images.
- Existing personal credentials, books, transcripts and full text are never uploaded to GitHub CI or public Issues.