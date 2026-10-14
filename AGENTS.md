# Agent Instructions / Hermes + OpenClaw

Project: WeRead Archive Agent (personal local ebook workflow)

## Contract

- Use `python wereadlab.py ... --json` from the repository directory. JSON status values are stable for downstream orchestration; never parse Chinese terminal prose as state.
- First call `doctor --json`. If `NEEDS_SETUP`, ensure Git and Python exist. `login` requires an interactive browser on the Windows desktop. Do not request, read, print, transmit, or commit raw cookies.
- Accept only an actual `https://weread.qq.com/web/reader/...` URL supplied by the user, or resolved by a separate permitted book-discovery integration; never assume `bookDetail` IDs are interchangeable.
- Before any full-book export, run `python wereadlab.py catalog URL --json` to obtain an authenticated local catalog snapshot.
- If a chapter has `CONTENT_SUSPICIOUS` due to image-only EPUB but provider wordCount suggests substantive text, use the TXT fallback built into the worker after verification; never mark the EPUB-only tiny text as complete. Preserve the original EPUB checkpoint and report recovered `txt_fallback_ordinals` for visual QA.
- After the queue is initialized, call `python wereadlab.py queue run --latest --limit 1 --json` for a strictly bounded sample; never call `export --full` as a substitute for queued resume. Diagnose any `WORKER_BLOCKED`, `WORKER_PARTIAL`, `COMPLETED_ARTIFACT_INTEGRITY_ERROR` before considering `--retry-failed`. Do not use high-rate parallel workers or read cookie contents.
- Next call `python wereadlab.py queue init --latest --json` and `queue status --latest --json`; `QUEUE_READY` means only chapter task metadata is queued. The capture worker and verified resume mechanism are not implemented yet; never suggest otherwise. Check `CATALOG_READY` and never treat an estimated count or `CATALOG_READY` as full-book completion.
- First `export URL --sample 2 --format epub --format md --json`; inspect report. After sample visual verification or prior user approval, `export URL --full --format epub --format pdf --format md --json`.
- If a sample succeeds at chapter text acquisition but fails due to local/remote images, prefer `python wereadlab.py repair --latest --format epub --format md --json` on the existing `.partial.epub` rather than re-fetching chapters. Do not disclose cookie values or book text. No success claim if `IMAGE_ASSETS_INCOMPLETE` remains.
- Only after all queue rows are COMPLETE and local SHA checks pass, call `python wereadlab.py book assemble --latest --format epub --format md --format pdf --json`; report CSS decoration warnings, catalog coverage and visual QA separately. `BOOK_FILES_READY_COMPLETENESS_UNVERIFIED` is not publication-ready or proof of verbatim completeness.
- Do not claim complete just because the CLI returns `FILES_READY_COMPLETENESS_UNVERIFIED`. Compare the reader catalog, check front/middle/end and image references. Ask the user only for steps that truly require a person.
- If `LOGIN_REQUIRED`, `MANUAL_VERIFICATION_REQUIRED`, `WEB_UNAVAILABLE`, or `ACCESS_RESTRICTED`, stop that book and report a succinct blocker. No captcha bypass, simulated user identity, fingerprint evasion, high-rate retry loops, or scraping inaccessible pages.
- `upstream --update` is an explicit controlled step, not performed before every export. Record SHA and re-run the fixture tests and 2-chapter sample after updates.
- Never commit/export credential files, copyrighted book contents, screenshots of real book chapters, or real user metadata into this public repository.
- External GUI/browser/login execution is on the user's authorized local computer only. GitHub Actions must only use synthetic fixtures and public repository metadata.

## Milestones

P0 CLI / offline EPUB tests; P1 sample real-book acceptance and report quality; P2 resume/checkpoints and canvas fallback; P3 local UI/EXE and NAS sync; P4 deeper catalog/visual QA and reading research integration.