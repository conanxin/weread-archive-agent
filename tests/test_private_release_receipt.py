"""Offline synthetic-only private release receipts; no Drive credentials."""
from pathlib import Path
import tempfile
import unittest

from tools.private_release_manifest import build_manifest,write_private_json
from tools.private_release_verify import verify_release


class PrivateReleaseTests(unittest.TestCase):
    def create_fixture(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder=Path(self.tmp.name)
        (folder/"sample.epub").write_bytes(b"synthetic EPUB fixture only")
        (folder/"sample.pdf").write_bytes(b"synthetic PDF fixture only")
        manifest=build_manifest(folder,["sample.epub","sample.pdf"],"fake-folder-123")
        cloud={
            "folder":{"id":"fake-folder-123","shared":False,
                      "permissions":[{"type":"user","role":"owner"}]},
            "files":[
                {"id":"cloud-"+row["name"],"name":row["name"],
                 "bytes":row["bytes"],"parent_ids":["fake-folder-123"],
                 "shared":False,"permissions":[{"type":"user","role":"owner"}],
                 "downloaded_sha256":row["sha256"]}
                for row in manifest["files"]
            ],
        }
        return folder,manifest,cloud

    def test_two_file_verified_success(self):
        root,manifest,cloud=self.create_fixture()
        result=verify_release(manifest,cloud)
        self.assertEqual(result["status"],"PRIVATE_DELIVERY_PASS")
        self.assertEqual(result["expected"],result["delivered"])
        self.assertNotIn("synthetic EPUB fixture",str(result))
        self.assertNotIn("cloud-sample.epub",str(result))
        self.assertEqual(verify_release(manifest,cloud),result)

    def test_root_wrong_parent_is_not_success(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"][0]["parent_ids"]=["root"]
        result=verify_release(manifest,cloud)
        self.assertEqual(result["status"],"PRIVATE_DELIVERY_INCOMPLETE")
        self.assertIn("WRONG_CLOUD_PARENT",[x["status"] for x in result["items"]])

    def test_missing_cloud_hash_is_not_success(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"][0].pop("downloaded_sha256")
        result=verify_release(manifest,cloud)
        self.assertIn("CLOUD_HASH_NOT_PROVEN",[x["status"] for x in result["items"]])

    def test_cloud_hash_mismatch_blocks(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"][0]["downloaded_sha256"]="0"*64
        result=verify_release(manifest,cloud)
        self.assertIn("CLOUD_SHA256_MISMATCH",[x["status"] for x in result["items"]])

    def test_owner_only_is_mandatory(self):
        _,manifest,cloud=self.create_fixture()
        cloud["folder"]["shared"]=True
        self.assertEqual(verify_release(manifest,cloud)["delivered"],0)
        cloud["folder"]["shared"]=False
        cloud["files"][0]["permissions"].append({"type":"anyone","role":"reader"})
        self.assertIn("OWNER_ONLY_NOT_PROVEN",[x["status"] for x in verify_release(manifest,cloud)["items"]])

    def test_duplicate_name_is_ambiguous(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"].append(dict(cloud["files"][0],id="cloud-duplicate"))
        self.assertIn("AMBIGUOUS_SAME_NAME",[x["status"] for x in verify_release(manifest,cloud)["items"]])

    def test_drive_metadata_returns_byte_sizes_as_strings(self):
        _,manifest,cloud=self.create_fixture()
        for x in cloud["files"]:
            x["bytes"]=str(x["bytes"])
        self.assertEqual(verify_release(manifest,cloud)["status"],"PRIVATE_DELIVERY_PASS")

    def test_missing_cloud_id_blocks(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"][0]["id"]=""
        self.assertIn("CLOUD_ID_UNRESOLVED",[x["status"] for x in verify_release(manifest,cloud)["items"]])

    def test_local_file_change_blocks(self):
        root,manifest,cloud=self.create_fixture()
        (root/"sample.pdf").write_bytes(b"tampered fixture")
        self.assertIn("LOCAL_FILE_CHANGED",[x["status"] for x in verify_release(manifest,cloud)["items"]])

    def test_incorrect_size_blocks(self):
        _,manifest,cloud=self.create_fixture()
        cloud["files"][0]["bytes"]+=1
        self.assertIn("CLOUD_BYTE_COUNT_MISMATCH",[x["status"] for x in verify_release(manifest,cloud)["items"]])

    def test_unsafe_paths_cannot_be_staged(self):
        root,_,_=self.create_fixture()
        for name in ("../secrets.txt",".env","cookie-file.txt","payload.exe","nested/path.epub"):
            with self.subTest(name=name),self.assertRaises(ValueError):
                build_manifest(root,[name],"fake-folder-123")

    def test_manifest_writer_is_idempotent_but_not_overwriting(self):
        root,manifest,_=self.create_fixture()
        target=root/"private-manifest.json"
        write_private_json(target,manifest)
        first=target.read_bytes()
        write_private_json(target,manifest)
        self.assertEqual(target.read_bytes(),first)
        with self.assertRaises(FileExistsError):
            write_private_json(target,{"status":"DIFFERENT"})


if __name__=="__main__":
    unittest.main()
