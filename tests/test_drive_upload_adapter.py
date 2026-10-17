"""Synthetic-only regression tests for Drive explicit-parent upload transport."""
from pathlib import Path
import hashlib
import tempfile
import unittest

from tools.private_release_manifest import build_manifest
from tools.drive_upload_adapter import (
    PlacementError, DriveAPI, CHUNK, checked_sources, md5_file, reconcile, owner_only,
)


class FakeDrive:
    def __init__(self, destination="fake-target"):
        self.target = destination
        self.objects = {}
        self.calls = []
        self.counter = 0
        self.folders = {
            destination: {"id": destination, "shared": False,
                          "permissions": [{"type": "user", "role": "owner"}]}
        }

    def add(self, name, data: bytes, parent, *, ident=None, shared=False):
        self.counter += 1
        fid = ident or f"f-{self.counter}"
        self.objects[fid] = {
            "id": fid, "name": name, "size": str(len(data)),
            "md5Checksum": hashlib.md5(data).hexdigest(),
            "parents": [parent], "shared": shared,
            "permissions": ([{"type": "user", "role": "owner"}] if not shared
                            else [{"type": "anyone", "role": "reader"}])
        }
        return fid

    def folder(self, fid):
        return dict(self.folders.get(fid) or self.objects[fid])

    def named(self, name):
        return [dict(f) for f in self.objects.values() if f["name"] == name]

    def move(self, fid, old, new):
        self.calls.append(("move", fid, old, new))
        assert self.objects[fid]["parents"] == [old]
        self.objects[fid]["parents"] = [new]
        return dict(self.objects[fid])

    def upload(self, path, target):
        self.calls.append(("upload", path.name, target))
        raw = path.read_bytes()
        return self.folder(self.add(path.name, raw, target))


class DriveUploadAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "part.epub").write_bytes(b"synthetic-epub-xyz")
        (self.root / "qa.json").write_bytes(b'{"status":"synthetic"}')
        self.manifest = build_manifest(self.root, ["part.epub", "qa.json"],
                                       "fake-target")
        self.drive = FakeDrive()

    def add_existing(self, name="part.epub", parent="root"):
        return self.drive.add(name, (self.root / name).read_bytes(), parent)

    def test_explicit_parent_on_creation(self):
        result = reconcile(self.manifest, self.drive, execute=True)
        self.assertEqual(result["status"], "UPLOAD_PLACEMENT_VERIFIED")
        self.assertEqual(result["expected"], 2)
        self.assertFalse(result["cloud_sha_verified"])
        self.assertEqual([a["action"] for a in result["actions"]],
                         ["CREATED", "CREATED"])
        self.assertEqual([c[2] for c in self.drive.calls], ["fake-target"] * 2)
        self.assertTrue(all(f["parents"] == ["fake-target"] for f in self.drive.objects.values()))

    def test_root_object_moved_same_id_not_reuploaded(self):
        fid = self.add_existing()
        result = reconcile(self.manifest, self.drive, execute=True)
        entry = next(a for a in result["actions"] if a["name"] == "part.epub")
        self.assertEqual(entry["id"], fid)
        self.assertEqual(entry["action"], "MOVED")
        self.assertIn(("move", fid, "root", "fake-target"), self.drive.calls)
        self.assertNotIn(("upload", "part.epub", "fake-target"), self.drive.calls)

    def test_repeat_call_reuses_same_objects(self):
        reconcile(self.manifest, self.drive, execute=True)
        self.drive.calls.clear()
        result = reconcile(self.manifest, self.drive, execute=True)
        self.assertEqual([x["action"] for x in result["actions"]], ["REUSED", "REUSED"])
        self.assertFalse(self.drive.calls)

    def test_plan_does_not_write(self):
        self.add_existing()
        result = reconcile(self.manifest, self.drive, execute=False)
        self.assertEqual(result["status"], "PLACEMENT_PLAN_ONLY")
        self.assertEqual([x["action"] for x in result["actions"]],
                         ["WOULD_MOVE", "WOULD_CREATE"])
        self.assertFalse(self.drive.calls)

    def test_duplicate_cloud_name_stops(self):
        self.add_existing()
        self.add_existing(parent="fake-target")
        with self.assertRaisesRegex(PlacementError, "DUPLICATE_REMOTE_FILENAME"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_same_name_wrong_bytes_stops_instead_of_overwriting(self):
        self.drive.add("part.epub", b"other-content", "root")
        with self.assertRaisesRegex(PlacementError, "REMOTE_BYTES_DIFFER"):
            reconcile(self.manifest, self.drive, execute=True)
        self.assertFalse(self.drive.calls)

    def test_same_size_wrong_hash_stops(self):
        original = (self.root / "part.epub").read_bytes()
        self.drive.add("part.epub", b"x" * len(original), "root")
        with self.assertRaisesRegex(PlacementError, "REMOTE_BYTES_DIFFER"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_malformed_acl_and_public_folder_stop(self):
        self.drive.folders["fake-target"]["shared"] = True
        with self.assertRaisesRegex(PlacementError, "DESTINATION_NOT_OWNER_ONLY"):
            reconcile(self.manifest, self.drive, execute=True)
        self.drive.folders["fake-target"]["shared"] = False
        ident = self.add_existing()
        self.drive.objects[ident]["permissions"] = [
            {"type": "anyone", "role": "reader"}]
        with self.assertRaisesRegex(PlacementError, "REMOTE_NOT_OWNER_ONLY"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_ambiguous_multiple_parent_stops(self):
        fid = self.add_existing()
        self.drive.objects[fid]["parents"] = ["root", "fake-other"]
        with self.assertRaisesRegex(PlacementError, "CLOUD_PARENT_AMBIGUOUS"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_local_byte_change_stops(self):
        (self.root / "part.epub").write_bytes(b"new-content")
        with self.assertRaisesRegex(PlacementError, "LOCAL_MANIFEST_CHANGED"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_reject_untrusted_manifest_directory(self):
        invalid = dict(self.manifest, local_directory="/does/not/exist")
        with self.assertRaises(PlacementError):
            checked_sources(invalid)

    def test_cloud_metadata_missing_hash_is_not_proof(self):
        fid = self.add_existing()
        del self.drive.objects[fid]["md5Checksum"]
        with self.assertRaisesRegex(PlacementError, "REMOTE_BYTES_DIFFER"):
            reconcile(self.manifest, self.drive, execute=True)

    def test_final_gate_remains_separate(self):
        self.assertTrue(owner_only(self.drive.folder("fake-target")))
        result = reconcile(self.manifest, self.drive, execute=True)
        self.assertFalse(result["cloud_sha_verified"])
        self.assertNotIn("PRIVATE_DELIVERY_PASS", str(result))

    def test_hash_helper_matches_python_standard(self):
        target = self.root / "part.epub"
        self.assertEqual(md5_file(target), hashlib.md5(target.read_bytes()).hexdigest())


class StubResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeUploadSession:
    def __init__(self, *, invalid_location=False, bad_range=False):
        self.headers = {}
        self.init_payload = None
        self.sent_ranges = []
        self.invalid_location = invalid_location
        self.bad_range = bad_range

    def post(self, url, *, params, json, headers, timeout):
        self.init_payload = {
            "url": url, "params": params, "body": json,
            "headers": headers, "timeout": timeout,
        }
        location = ("https://attacker.example/upload" if self.invalid_location
                    else "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture")
        return StubResponse(200, headers={"Location": location})

    def put(self, url, *, data, headers, timeout):
        self.sent_ranges.append((headers["Content-Range"], len(data)))
        spec = headers["Content-Range"]
        finished = int(spec.split("-")[-1].split("/")[0]) + 1
        total = int(spec.split("/")[-1])
        if finished == total:
            return StubResponse(200, {"id": "created-fixture"})
        return StubResponse(308, headers={
            "Range": ("bytes=0-999999999" if self.bad_range
                      else "bytes=0-" + str(finished - 1))
        })


class DriveWireFormatTests(unittest.TestCase):
    def test_resumable_upload_posts_parent_and_byte_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / "synthetic.epub"
            filename.write_bytes(b"f" * (CHUNK + 17))
            session = FakeUploadSession()
            drive = DriveAPI("synthetic-oauth-for-unit-test", session=session)
            response = drive.upload(filename, "expected-folder")
            self.assertEqual(response["id"], "created-fixture")
            self.assertEqual(session.init_payload["body"]["parents"],
                             ["expected-folder"])
            self.assertEqual(session.init_payload["body"]["name"], "synthetic.epub")
            self.assertEqual(session.init_payload["headers"]["X-Upload-Content-Length"],
                             str(CHUNK + 17))
            self.assertEqual(session.sent_ranges, [
                (f"bytes 0-{CHUNK - 1}/{CHUNK + 17}", CHUNK),
                (f"bytes {CHUNK}-{CHUNK + 16}/{CHUNK + 17}", 17),
            ])
            self.assertTrue(session.headers["Authorization"].startswith("Bearer "))

    def test_resumable_session_rejects_non_google_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / "synthetic.epub"
            filename.write_bytes(b"fake")
            drive = DriveAPI("fake", session=FakeUploadSession(invalid_location=True))
            with self.assertRaisesRegex(PlacementError, "INVALID_GOOGLE_UPLOAD_SESSION"):
                drive.upload(filename, "expected-folder")

    def test_bad_308_range_stops_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / "synthetic.epub"
            filename.write_bytes(b"z" * (CHUNK + 1))
            drive = DriveAPI("fake", session=FakeUploadSession(bad_range=True))
            with self.assertRaisesRegex(PlacementError, "UPLOAD_RANGE_INVALID"):
                drive.upload(filename, "expected-folder")


if __name__ == "__main__":
    unittest.main()
