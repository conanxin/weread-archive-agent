"""Weekly GitHub Actions watch: create a deduplicated issue for changed upstream HEAD.

No WeRead API, cookies, book contents or personal data are used.
"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def gh(*args):
    process = subprocess.run(["gh", *args], text=True, capture_output=True,
                             encoding="utf-8", check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or f"gh failed: {args}")
    return process.stdout.strip()


def changed_heads(pinned: dict, actual: dict, existing_titles: set[str]):
    plans = []
    for repo, baseline in pinned.items():
        sha = actual[repo]
        title = f"[Upstream] {repo} changed: {sha[:10]}"
        if sha != baseline and title not in existing_titles:
            plans.append((repo, baseline, sha, title))
    return plans


def main():
    config = json.loads((ROOT / ".github/upstreams.json").read_text(encoding="utf-8"))
    actual = {repo: gh("api", f"repos/{repo}/commits/main", "--jq", ".sha")
              for repo in config}
    existing = json.loads(gh("issue", "list", "--state", "all", "--limit", "250",
                             "--json", "title"))
    titles = {issue["title"] for issue in existing}
    for repo, previous, current, title in changed_heads(config, actual, titles):
        body = (f"Weekly public upstream monitor found a new commit.\n\n"
                f"- Source: https://github.com/{repo}\n"
                f"- Pinned in this repository: `{previous}`\n"
                f"- Current main HEAD: `{current}`\n\n"
                "Review diffs and run offline tests, then perform a human-approved "
                "two-chapter smoke test. Do not auto-merge upstream code or use live "
                "user cookies in GitHub Actions. Update `.github/upstreams.json` "
                "only after compatibility review.")
        gh("issue", "create", "--title", title, "--body", body)
        print("Created review issue:", title)
    if not changed_heads(config, actual, titles):
        print("No unreported upstream HEAD changes")


if __name__ == "__main__":
    main()