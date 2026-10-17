"""Google Drive placement adapter for personal, owner-only book releases.

Uploads raw bytes with an explicit parent using Drive v3 resumable upload.
A completed cloud object is reused, or moved by its original ID if misplaced.
This is a transport/placement gate, NOT the final independent cloud SHA gate.

Authorization: a short-lived OAuth access token from an environment variable.
Never include credentials or private manifests in the public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from tools.private_release_manifest import SCHEMA, hash_file

API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FIELDS = "id,name,size,md5Checksum,parents,shared,permissions(type,role)"
CHUNK = 8 * 1024 * 1024


class PlacementError(RuntimeError):
    """An ambiguous, unauthenticated or inconsistent cloud state."""


def md5_file(path: Path) -> str:
    md5 = hashlib.md5()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(part)
    return md5.hexdigest()


def owner_only(meta: dict) -> bool:
    perms = meta.get("permissions")
    return (meta.get("shared") is False and isinstance(perms, list)
            and len(perms) == 1 and perms[0].get("type") == "user"
            and perms[0].get("role") == "owner")


def checked_sources(manifest: dict) -> tuple[Path, str, list[dict]]:
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "STAGED":
        raise PlacementError("INVALID_PRIVATE_MANIFEST")
    root = Path(str(manifest.get("local_directory", ""))).resolve()
    target = manifest.get("target_folder_id")
    files = manifest.get("files")
    if not root.is_dir() or not isinstance(target, str) or not target or "/" in target:
        raise PlacementError("INVALID_TARGET_FOLDER")
    if not isinstance(files, list) or not files:
        raise PlacementError("NO_MANIFEST_FILES")
    names = [r.get("name") for r in files if isinstance(r, dict)]
    if len(names) != len(files) or len(set(names)) != len(names):
        raise PlacementError("DUPLICATE_OR_INVALID_NAMES")
    for item in files:
        name = item["name"]
        if (not isinstance(name, str) or name != Path(name).name
                or not name or name.startswith(".") or "\\" in name):
            raise PlacementError("UNSAFE_MANIFEST_NAME")
        file = root / name
        if (file.is_symlink() or not file.is_file()
                or not file.resolve().is_relative_to(root)):
            raise PlacementError("UNSAFE_OR_MISSING_LOCAL_FILE")
        if file.stat().st_size != item.get("bytes") or hash_file(file) != item.get("sha256"):
            raise PlacementError("LOCAL_MANIFEST_CHANGED")
    return root, target, files


def same_bytes(meta: dict, item: dict, md5: str) -> bool:
    return (str(meta.get("size")) == str(item["bytes"])
            and meta.get("md5Checksum") == md5)


def single_parent(meta: dict) -> str:
    parents = meta.get("parents")
    if not isinstance(parents, list) or len(parents) != 1 or not parents[0]:
        raise PlacementError("CLOUD_PARENT_AMBIGUOUS")
    return parents[0]


class DriveAPI:
    """Small official Drive REST client; accepts an injectable requests session."""

    def __init__(self, token: str, session=None):
        if not token:
            raise PlacementError("GOOGLE_ACCESS_TOKEN_REQUIRED")
        if session is None:
            import requests
            session = requests.Session()
        self.http = session
        self.http.headers.update({"Authorization": "Bearer " + token})

    @staticmethod
    def _json(response, statuses=(200,)):
        if response.status_code not in statuses:
            raise PlacementError("GOOGLE_HTTP_" + str(response.status_code))
        return response.json()

    def folder(self, fid: str) -> dict:
        response = self.http.get(API + "/files/" + fid,
                                 params={"fields": FIELDS, "supportsAllDrives": "true"},
                                 timeout=50)
        return self._json(response)

    def named(self, name: str) -> list[dict]:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = "name = '" + escaped + "' and trashed = false"
        rows, page = [], None
        while True:
            params = {"q": query, "fields": "nextPageToken,files(" + FIELDS + ")",
                      "pageSize": 1000, "spaces": "drive"}
            if page:
                params["pageToken"] = page
            payload = self._json(self.http.get(API + "/files", params=params, timeout=50))
            rows += payload.get("files", [])
            page = payload.get("nextPageToken")
            if not page:
                break
        return rows

    def move(self, fid: str, previous: str, target: str) -> dict:
        response = self.http.patch(
            API + "/files/" + fid,
            params={"addParents": target, "removeParents": previous,
                    "fields": FIELDS, "supportsAllDrives": "true"}, timeout=90)
        return self._json(response)

    def upload(self, path: Path, target: str) -> dict:
        size = path.stat().st_size
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        response = self.http.post(
            UPLOAD_API, params={"uploadType": "resumable", "fields": FIELDS},
            json={"name": path.name, "parents": [target]},
            headers={"X-Upload-Content-Type": mime,
                     "X-Upload-Content-Length": str(size)}, timeout=90)
        if response.status_code not in (200, 201):
            raise PlacementError("DRIVE_UPLOAD_SESSION_HTTP_" + str(response.status_code))
        location = response.headers.get("Location", "")
        parsed = urlsplit(location)
        if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
            raise PlacementError("INVALID_GOOGLE_UPLOAD_SESSION")
        offset = 0
        with path.open("rb") as f:
            while offset < size:
                f.seek(offset)
                data = f.read(min(CHUNK, size - offset))
                if not data:
                    raise PlacementError("UPLOAD_SOURCE_EOF")
                end = offset + len(data) - 1
                r = self.http.put(
                    location, data=data,
                    headers={"Content-Type": mime,
                             "Content-Length": str(len(data)),
                             "Content-Range": f"bytes {offset}-{end}/{size}"},
                    timeout=240)
                if r.status_code in (200, 201):
                    if end != size - 1:
                        raise PlacementError("UPLOAD_FINISHED_BEFORE_EOF")
                    return self._json(r, (200, 201))
                if r.status_code != 308:
                    raise PlacementError("DRIVE_UPLOAD_CHUNK_HTTP_" + str(r.status_code))
                acknowledged = re.fullmatch(r"bytes=0-(\d+)", r.headers.get("Range", ""))
                if not acknowledged:
                    raise PlacementError("UPLOAD_RANGE_NOT_ACKNOWLEDGED")
                next_byte = int(acknowledged.group(1)) + 1
                if next_byte <= offset or next_byte > end + 1:
                    raise PlacementError("UPLOAD_RANGE_INVALID")
                offset = next_byte
        raise PlacementError("UPLOAD_NO_FINAL_RESPONSE")


def reconcile(manifest: dict, drive, *, execute: bool = False) -> dict:
    root, target, entries = checked_sources(manifest)
    if not owner_only(drive.folder(target)):
        raise PlacementError("DESTINATION_NOT_OWNER_ONLY")
    rows = []
    for entry in entries:
        name = entry["name"]
        local = root / name
        md5 = md5_file(local)
        matches = drive.named(name)
        if len(matches) > 1:
            raise PlacementError("DUPLICATE_REMOTE_FILENAME")
        if matches:
            remote = matches[0]
            if not owner_only(remote):
                raise PlacementError("REMOTE_NOT_OWNER_ONLY")
            if not same_bytes(remote, entry, md5):
                raise PlacementError("REMOTE_BYTES_DIFFER")
            previous = single_parent(remote)
            if previous == target:
                action = "REUSED"
            elif execute:
                drive.move(remote["id"], previous, target)
                action = "MOVED"
            else:
                action = "WOULD_MOVE"
            fid = remote["id"]
        elif execute:
            uploaded = drive.upload(local, target)
            if not uploaded.get("id"):
                raise PlacementError("NEW_UPLOAD_ID_MISSING")
            fid = uploaded["id"]
            action = "CREATED"
        else:
            rows.append({"name": name, "action": "WOULD_CREATE"})
            continue
        if execute or action == "REUSED":
            verified = drive.folder(fid)
            if (verified.get("name") != name or not owner_only(verified)
                    or single_parent(verified) != target
                    or not same_bytes(verified, entry, md5)):
                raise PlacementError("POST_OPERATION_METADATA_MISMATCH")
        rows.append({"name": name, "action": action, "id": fid})
    return {"status": "UPLOAD_PLACEMENT_VERIFIED" if execute else "PLACEMENT_PLAN_ONLY",
            "expected": len(entries), "handled": len(rows),
            "actions": rows, "cloud_sha_verified": False,
            "note": "Run existing private_release_verify after independent full cloud-byte SHA256."}


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit-parent Drive placement adapter")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--token-env", default="GOOGLE_DRIVE_ACCESS_TOKEN")
    parser.add_argument("--execute", action="store_true", help="Create/move missing files")
    args = parser.parse_args()
    if args.receipt.exists():
        raise PlacementError("PRIVATE_RECEIPT_EXISTS")
    token = os.environ.get(args.token_env, "")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = reconcile(manifest, DriveAPI(token), execute=args.execute)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"status": report["status"], "expected": report["expected"],
                      "handled": report["handled"], "cloud_sha_verified": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
