# Agent Instructions / Hermes + OpenClaw

Project: WeRead Archive Agent (personal local ebook workflow)

## Contract

- Use `python wereadlab.py ... --json` from the repository directory. JSON status values are stable for downstream orchestration; never parse Chinese terminal prose as state.
- First call `doctor --json`. If `NEEDS_SETUP`, ensure Git and Python exist. `login` requires an interactive browser on the Windows desktop. Do not request, read, print, transmit, or commit raw cookies.
- Accept only an actual `https://weread.qq.com/web/reader/...` URL supplied by the user, or resolved by a separate permitted book-discovery integration; never assume `bookDetail` IDs are interchangeable.
- First `export URL --sample 2 --format epub --format md --json`; inspect report. After sample visual verification or prior user approval, `export URL --full --format epub --format pdf --format md --json`.
- If a sample succeeds at chapter text acquisition but fails due to local/remote images, prefer `python wereadlab.py repair --latest --format epub --format md --json` on the existing `.partial.epub` rather than re-fetching chapters. Do not disclose cookie values or book text. No success claim if `IMAGE_ASSETS_INCOMPLETE` remains.
- Do not claim complete just because the CLI returns `FILES_READY_COMPLETENESS_UNVERIFIED`. Compare the reader catalog, check front/middle/end and image references. Ask the user only for steps that truly require a person.
- If `LOGIN_REQUIRED`, `MANUAL_VERIFICATION_REQUIRED`, `WEB_UNAVAILABLE`, or `ACCESS_RESTRICTED`, stop that book and report a succinct blocker. No captcha bypass, simulated user identity, fingerprint evasion, high-rate retry loops, or scraping inaccessible pages.
- `upstream --update` is an explicit controlled step, not performed before every export. Record SHA and re-run the fixture tests and 2-chapter sample after updates.
- Never commit/export credential files, copyrighted book contents, screenshots of real book chapters, or real user metadata into this public repository.
- External GUI/browser/login execution is on the user's authorized local computer only. GitHub Actions must only use synthetic fixtures and public repository metadata.

## Milestones

P0 CLI / offline EPUB tests; P1 sample real-book acceptance and report quality; P2 resume/checkpoints and canvas fallback; P3 local UI/EXE and NAS sync; P4 deeper catalog/visual QA and reading research integration.