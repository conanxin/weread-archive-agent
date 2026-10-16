"""P3-E: prepare a private, deterministic manifest before any cloud upload.

No network, account, cookie or browser interaction. Output belongs under
.local/ and must never be committed with real book filenames or hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 1
EXTENSIONS = {".epub",".pdf",".zip",".md",".txt",".jpg",".jpeg",".png",".json"}
SENSITIVE = ("cookie","token","secret","credential","session",".env")


def hash_file(file: Path) -> str:
    digest=hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(directory: Path, names: list[str], folder_id: str) -> dict:
    root=directory.resolve(strict=True)
    if not root.is_dir() or not folder_id or "/" in folder_id:
        raise ValueError("INVALID_PRIVATE_DESTINATION")
    if not names or len(names)!=len(set(names)):
        raise ValueError("EMPTY_OR_DUPLICATED_FILE_LIST")
    entries=[]
    for name in names:
        if (not name or name!=Path(name).name or "\\" in name or
                name.startswith(".") or Path(name).suffix.lower() not in EXTENSIONS or
                any(part in name.casefold() for part in SENSITIVE)):
            raise ValueError("INVALID_OR_SENSITIVE_FILE_NAME")
        file=root/name
        if (file.is_symlink() or not file.is_file()
                or not file.resolve().is_relative_to(root) or file.stat().st_size<=0):
            raise ValueError("STAGED_FILE_MISSING_OR_UNSAFE")
        entries.append({"name":name,"bytes":file.stat().st_size,"sha256":hash_file(file)})
    return {"schema":SCHEMA,"status":"STAGED","local_directory":str(root),
            "target_folder_id":folder_id,
            "files":sorted(entries,key=lambda x:x["name"]),
            "note":"Manifest only; upload and cloud verification have not been performed."}


def write_private_json(dest: Path, value: dict) -> None:
    content=json.dumps(value,ensure_ascii=False,indent=2)+"\n"
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        if dest.read_text(encoding="utf-8")==content:
            return
        raise FileExistsError("PRIVATE_RECEIPT_ALREADY_EXISTS_DIFFERENT")
    staged=dest.with_suffix(dest.suffix+".writing")
    if staged.exists():
        raise FileExistsError("INCOMPLETE_PRIOR_WRITE")
    try:
        staged.write_text(content,encoding="utf-8")
        os.replace(staged,dest)
    finally:
        staged.unlink(missing_ok=True)


def main() -> None:
    p=argparse.ArgumentParser(description="Prepare private cloud-release file manifest")
    p.add_argument("--directory",type=Path,required=True)
    p.add_argument("--files",nargs="+",required=True)
    p.add_argument("--target-folder-id",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    document=build_manifest(args.directory,args.files,args.target_folder_id)
    write_private_json(args.output,document)
    print(json.dumps({"status":document["status"],"files":len(document["files"]),
                      "output":str(args.output)},ensure_ascii=False))


if __name__=="__main__":
    main()
