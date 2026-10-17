"""One-command live REST smoke of the local Drive adapter using synthetic TXT only.

Requires previously approved desktop OAuth. Creates one temporary private
folder/file, exercises explicit parent/reuse/root move, checks full cloud-byte
SHA256 via Drive files.get?alt=media and existing generic release verifier,
then removes only its own synthetic test objects. Never handles real books.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from tools.drive_oauth_bootstrap import get_access_token
from tools.drive_upload_adapter import (
    API, FIELDS, DriveAPI, PlacementError, owner_only, reconcile, single_parent
)
from tools.private_release_manifest import build_manifest
from tools.private_release_verify import verify_release


def _request_json(response, statuses: tuple[int, ...]) -> dict:
    if response.status_code not in statuses:
        raise PlacementError("GOOGLE_TEST_REQUEST_HTTP_" + str(response.status_code))
    return response.json()


def live_smoke(token: str, *, local_directory: Path) -> dict:
    """Perform one synthetic provider test. Only this function performs writes."""
    drive = DriveAPI(token)
    label = uuid.uuid4().hex[:12]
    destination_name = "P8C_Synthetic_Private_" + label
    file_name = "P8C_Synthetic_" + label + ".txt"
    payload = b"P8-C synthetic Drive adapter live fixture\nno personal or book content\n"
    folder_id: str | None = None
    created_file_id: str | None = None
    cleanup_errors: list[str] = []
    audit = {"status": "P8C_REAL_API_SMOKE_INCOMPLETE",
             "live_google_drive_used": True,
             "synthetic_content_only": True,
             "private_old_books_untouched": True}
    try:
        response = drive.http.post(
            API + "/files", params={"fields": FIELDS},
            json={"name": destination_name,
                  "mimeType": "application/vnd.google-apps.folder",
                  "parents": ["root"]}, timeout=90)
        meta = _request_json(response, (200, 201))
        folder_id = meta.get("id")
        if not folder_id:
            raise PlacementError("LIVE_TEST_FOLDER_ID_MISSING")
        folder = drive.folder(folder_id)
        if not owner_only(folder):
            raise PlacementError("LIVE_TEST_FOLDER_ACL_NOT_OWNER_ONLY")
        root_id = single_parent(folder)

        local_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p8c_live_", dir=str(local_directory)) as temp:
            local = Path(temp)
            (local / file_name).write_bytes(payload)
            manifest = build_manifest(local, [file_name], folder_id)

            dry = reconcile(manifest, drive, execute=False)
            if dry["status"] != "PLACEMENT_PLAN_ONLY" or dry["actions"][0]["action"] != "WOULD_CREATE":
                raise PlacementError("LIVE_PLAN_UNEXPECTED_REMOTE_FILE")

            first = reconcile(manifest, drive, execute=True)
            if first["status"] != "UPLOAD_PLACEMENT_VERIFIED" or first["actions"][0]["action"] != "CREATED":
                raise PlacementError("LIVE_UPLOAD_NOT_CREATED_IN_TARGET")
            created_file_id = first["actions"][0]["id"]

            repeated = reconcile(manifest, drive, execute=True)
            if repeated["actions"][0]["action"] != "REUSED":
                raise PlacementError("LIVE_REPEAT_UPLOAD_NOT_IDEMPOTENT")
            if repeated["actions"][0]["id"] != created_file_id:
                raise PlacementError("LIVE_REUSE_FILE_ID_CHANGED")

            moved = drive.move(created_file_id, folder_id, root_id)
            if single_parent(moved) != root_id or moved["id"] != created_file_id:
                raise PlacementError("LIVE_TEST_ROOT_MOVE_INVALID")
            restored = reconcile(manifest, drive, execute=True)
            if restored["actions"][0]["action"] != "MOVED":
                raise PlacementError("LIVE_TEST_WRONG_PARENT_NOT_REPAIRED")
            if restored["actions"][0]["id"] != created_file_id:
                raise PlacementError("LIVE_TEST_MOVE_CHANGED_FILE_ID")

            current = drive.folder(created_file_id)
            if not owner_only(current) or single_parent(current) != folder_id:
                raise PlacementError("LIVE_TEST_FINAL_PARENT_OR_ACL_MISMATCH")

            # Independent full-byte download: not a local hash echoed as cloud proof.
            download = drive.http.get(
                API + "/files/" + created_file_id,
                params={"alt": "media"}, stream=True, timeout=(30, 120))
            if download.status_code != 200:
                raise PlacementError("LIVE_CLOUD_DOWNLOAD_HTTP_" + str(download.status_code))
            digest = hashlib.sha256()
            bytes_seen = 0
            with download:
                for chunk in download.iter_content(1024 * 1024):
                    if chunk:
                        digest.update(chunk)
                        bytes_seen += len(chunk)
            expected = manifest["files"][0]
            if bytes_seen != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
                raise PlacementError("LIVE_CLOUD_SHA256_OR_BYTES_MISMATCH")

            observed = {"folder": {
                "id": folder["id"], "shared": folder.get("shared"),
                "permissions": folder.get("permissions")},
                "files": [{
                    "name": current["name"], "id": current["id"],
                    "bytes": current["size"], "parent_ids": current["parents"],
                    "shared": current.get("shared"),
                    "permissions": current.get("permissions"),
                    "downloaded_sha256": digest.hexdigest(),
                }]}
            result = verify_release(manifest, observed)
            if result["status"] != "PRIVATE_DELIVERY_PASS" or result["delivered"] != 1:
                raise PlacementError("GENERIC_GATE_REJECTED_LIVE_CLOUD_BYTES")
            audit.update(status="P8C_LOCAL_ADAPTER_REAL_API_PASS",
                         size_bytes=bytes_seen,
                         plan="PLACEMENT_PLAN_ONLY",
                         create="CREATED", repeat="REUSED", wrong_parent_repair="MOVED",
                         original_id_preserved=True,
                         owner_only=True,
                         independent_cloud_sha256=True,
                         generic_verify="PRIVATE_DELIVERY_PASS",
                         whole_book_human_signoff="NOT_APPLICABLE_SYNTHETIC")
    finally:
        # This cleanup touches only two IDs created inside this test.
        for kind, fid in (("file", created_file_id), ("folder", folder_id)):
            if fid:
                try:
                    deleted = drive.http.delete(
                        API + "/files/" + fid, timeout=50)
                    if deleted.status_code not in (200, 204):
                        cleanup_errors.append(kind + "_HTTP_" + str(deleted.status_code))
                except Exception:
                    cleanup_errors.append(kind + "_CLEANUP_FAILED")
        audit["cleanup_errors"] = cleanup_errors
        audit["temporary_cloud_objects_deleted"] = not cleanup_errors
    if cleanup_errors:
        audit["status"] = "P8C_REAL_API_SMOKE_CLEANUP_INCOMPLETE"
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Google Drive test using synthetic file only")
    parser.add_argument("--oauth-client-json", type=Path)
    parser.add_argument("--oauth-token-cache", type=Path,
                        default=Path(".local/google_drive_oauth_user.json"))
    parser.add_argument("--authorize", action="store_true")
    parser.add_argument("--local-directory", type=Path, default=Path(".local"))
    parser.add_argument("--receipt", type=Path,
                        default=Path(".local/p8c_google_drive_rest_live_smoke.json"))
    args = parser.parse_args()
    if args.receipt.exists():
        raise PlacementError("LIVE_TEST_RECEIPT_ALREADY_EXISTS")
    token = get_access_token(token_cache=args.oauth_token_cache,
                             client_json=args.oauth_client_json,
                             authorize=args.authorize)
    evidence = live_smoke(token, local_directory=args.local_directory)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "independent_cloud_sha256": evidence.get("independent_cloud_sha256", False),
        "temporary_objects_deleted": evidence["temporary_cloud_objects_deleted"],
    }))
    return 0 if evidence["status"] == "P8C_LOCAL_ADAPTER_REAL_API_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
