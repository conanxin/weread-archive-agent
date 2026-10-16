"""P3-E: fail-closed, read-only cloud delivery receipt verification.

The observed JSON must be assembled from trusted Drive metadata plus SHA256
of downloaded *cloud* bytes, not from a browser toast or local file path.
This module neither uploads nor moves files. Observations stay private.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.private_release_manifest import SCHEMA, hash_file, write_private_json


def _owner_only(perms: object) -> bool:
    return (isinstance(perms,list) and len(perms)==1
            and isinstance(perms[0],dict)
            and perms[0].get("type")=="user"
            and perms[0].get("role")=="owner")


def verify_release(manifest: dict, observed: dict) -> dict:
    if manifest.get("schema")!=SCHEMA:
        raise ValueError("UNSUPPORTED_MANIFEST_SCHEMA")
    folder_id=manifest.get("target_folder_id")
    expected=manifest.get("files")
    if not folder_id or not isinstance(expected,list) or not expected:
        raise ValueError("INVALID_MANIFEST")
    folder=observed.get("folder") or {}
    folder_ok=(folder.get("id")==folder_id
               and folder.get("shared") is False
               and _owner_only(folder.get("permissions")))
    seen: dict[str,list[dict]]={}
    if not isinstance(observed.get("files"),list):
        raise ValueError("INVALID_CLOUD_OBSERVATIONS")
    for data in observed["files"]:
        if isinstance(data,dict) and isinstance(data.get("name"),str):
            seen.setdefault(data["name"],[]).append(data)
    root=Path(str(manifest.get("local_directory",""))).resolve()
    used_ids=set()
    rows=[]
    for source in expected:
        name=source["name"]
        local=(root/name).resolve()
        hits=seen.get(name,[])
        matched=hits[0] if len(hits)==1 else None
        if not local.is_relative_to(root) or not local.is_file():
            status="LOCAL_FILE_MISSING"
        elif hash_file(local)!=source.get("sha256") or local.stat().st_size!=source.get("bytes"):
            status="LOCAL_FILE_CHANGED"
        elif len(hits)>1:
            status="AMBIGUOUS_SAME_NAME"
        elif not matched or not matched.get("id"):
            status="CLOUD_ID_UNRESOLVED"
        elif matched["id"] in used_ids:
            status="CLOUD_ID_DUPLICATED"
        elif matched.get("bytes")!=source["bytes"]:
            status="CLOUD_BYTE_COUNT_MISMATCH"
        elif folder_id not in (matched.get("parent_ids") or []):
            status="WRONG_CLOUD_PARENT"
        elif not folder_ok or matched.get("shared") is not False or not _owner_only(matched.get("permissions")):
            status="OWNER_ONLY_NOT_PROVEN"
        elif not matched.get("downloaded_sha256"):
            status="CLOUD_HASH_NOT_PROVEN"
        elif matched["downloaded_sha256"]!=source["sha256"]:
            status="CLOUD_SHA256_MISMATCH"
        else:
            status="DELIVERED"
        if matched and matched.get("id"):
            used_ids.add(matched["id"])
        rows.append({"name":name,"status":status})
    complete=sum(x["status"]=="DELIVERED" for x in rows)
    return {
        "status":"PRIVATE_DELIVERY_PASS" if complete==len(rows)
                 else "PRIVATE_DELIVERY_INCOMPLETE",
        "expected":len(rows),"delivered":complete,
        "owner_only_folder_verified":folder_ok,"items":rows,
        "note":"DELIVERED requires file ID, true parent, size, owner-only permissions and independently downloaded cloud SHA256."
    }


def main():
    p=argparse.ArgumentParser(description="Verify private Drive metadata and cloud hashes")
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--observed",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    report=verify_release(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        json.loads(args.observed.read_text(encoding="utf-8")))
    write_private_json(args.output,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report["status"]!="PRIVATE_DELIVERY_PASS":
        raise SystemExit(2)


if __name__=="__main__":
    main()
