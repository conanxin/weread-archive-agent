"""P2-D2: metadata-only audit of CSS image references in chapter EPUBs.

Runs offline. Reports no book text, chapter titles, asset names, URLs, cookie values
or full CSS selectors. Does not change any EPUB or mark fidelity verified.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from html.parser import HTMLParser
import hashlib
import html
import json
from pathlib import Path
import posixpath
import re
import urllib.parse
import zipfile

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
URL = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
SIMPLE_CLASS = re.compile(r"\.([A-Za-z_][A-Za-z0-9_-]*)\Z")
COMMENTS = re.compile(r"/\*.*?\*/", re.DOTALL)


class ClassIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts: Counter[str] = Counter()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "class" and value:
                self.counts.update(value.split())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _local_path(css_path: str, ref: str) -> str | None:
    u = urllib.parse.urlsplit(html.unescape(ref))
    if u.scheme or ref.startswith(("//", "#")) or not u.path:
        return None
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(css_path), urllib.parse.unquote(u.path))
    )


def audit_css_sources(files: list[Path]) -> dict:
    """Inspect source EPUBs, count occurrences and group duplicate missing URLs."""
    records = []
    for ordinal, path in enumerate(files, 1):
        if not path.is_file():
            raise FileNotFoundError("CHAPTER_EPUB_MISSING")
        with zipfile.ZipFile(path) as epub:
            if epub.testzip() is not None:
                raise ValueError("CHAPTER_ZIP_CRC_FAIL")
            names = set(epub.namelist())
            classes = ClassIndex()
            for name in names:
                if name.lower().endswith((".xhtml", ".html", ".htm")):
                    classes.feed(epub.read(name).decode("utf-8-sig", errors="replace"))
            for name in sorted(names):
                if not name.lower().endswith(".css"):
                    continue
                css = COMMENTS.sub("", epub.read(name).decode("utf-8-sig", errors="replace"))
                for selector, declarations in RULE.findall(css):
                    selector = selector.strip()
                    for declaration in declarations.split(";"):
                        if ":" not in declaration:
                            continue
                        prop, value = declaration.split(":", 1)
                        prop = prop.strip().lower()
                        for match in URL.finditer(value):
                            ref = html.unescape(match.group(2).strip())
                            if ref.startswith("data:"):
                                continue
                            local = _local_path(name, ref)
                            if local is not None and local in names:
                                continue
                            m = SIMPLE_CLASS.fullmatch(selector)
                            count = classes.counts.get(m.group(1), 0) if m else None
                            reason = (
                                "UNUSED_SIMPLE_CLASS" if count == 0 and m
                                else "USED_SIMPLE_CLASS" if count and m
                                else "UNKNOWN_OR_COMPLEX_SELECTOR"
                            )
                            # Same missing path may occur in numerous source
                            # chapter EPUBs. It must not be counted as N distinct images.
                            records.append({
                                "ordinal": ordinal,
                                "resource_sha16": _digest(local or ref),
                                "selector_sha16": _digest(selector),
                                "css_property": prop,
                                "selector_usage": reason,
                                "used_elements": count,
                                "reference_kind": "local" if local else "nonlocal",
                            })
    resource_groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        resource_groups[r["resource_sha16"]].append(r)
    summary = {
        "status": "CSS_AUDIT_READY_FIDELITY_UNVERIFIED",
        "chapters_audited": len(files),
        "missing_reference_occurrences": len(records),
        "unique_missing_resources": len(resource_groups),
        "usage_classification": dict(Counter(
            r["selector_usage"] for r in records
        )),
        "properties": dict(Counter(r["css_property"] for r in records)),
        "resources": [
            {
                "resource_sha16": key,
                "occurrences": len(group),
                "ordinals": [r["ordinal"] for r in group],
                "selector_sha16_list": sorted({r["selector_sha16"] for r in group}),
                "usage_classification": dict(Counter(
                    r["selector_usage"] for r in group
                )),
            }
            for key, group in sorted(resource_groups.items())
        ],
        "note": (
            "An unused CSS class in static EPUB XHTML is evidence of low likely "
            "visual impact, not a substitute for checking the source reader layout. "
            "Unknown selectors or used classes require closer review."
        ),
    }
    return summary


def audit_book_directory(folder: Path) -> dict:
    chapters = folder / "chapters"
    items = sorted(
        path for path in chapters.glob("*.epub")
        if re.fullmatch(r"[0-9]{4}\.epub", path.name)
    )
    if not items:
        raise FileNotFoundError("NO_COMPLETE_CHAPTER_EPUBS")
    expected = [f"{i:04d}.epub" for i in range(1, len(items) + 1)]
    if [p.name for p in items] != expected:
        raise ValueError("CHAPTER_EPUB_ORDINAL_GAPS")
    return audit_css_sources(items)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline CSS EPUB fidelity audit")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Private local JSON report path")
    args = parser.parse_args()
    outcome = audit_book_directory(args.book_dir.resolve())
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(outcome, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
