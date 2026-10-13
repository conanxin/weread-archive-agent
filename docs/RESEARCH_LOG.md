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