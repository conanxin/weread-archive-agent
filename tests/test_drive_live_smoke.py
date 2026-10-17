"""Synthetic-only tests for the one-command live Drive smoke driver."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.drive_live_smoke import live_smoke
from tools.drive_upload_adapter import PlacementError


class Reply:
    def __init__(self, code, payload=None, chunks=()):
        self.status_code=code
        self.payload=payload or {}
        self.chunks=chunks

    def json(self):
        return self.payload

    def iter_content(self, size):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MockDriveREST:
    def __init__(self, *, tamper_download=False, public_folder=False,
                 fail_delete=False):
        self.meta={}
        self.payload={}
        self.deleted=[]
        self.calls=[]
        self.folder_index=0
        self.tamper_download=tamper_download
        self.public_folder=public_folder
        self.fail_delete=fail_delete
        self.http=self

    def _owner(self):
        return [{"type":"user","role":"owner"}]

    def post(self, url, *, params, json, timeout):
        self.folder_index+=1
        fid="folder-"+str(self.folder_index)
        self.meta[fid]={"id":fid,"name":json["name"],"parents":["root-id"],
                        "shared":self.public_folder,
                        "permissions":self._owner() if not self.public_folder
                        else [{"type":"anyone","role":"reader"}]}
        return Reply(200,self.meta[fid])

    def named(self, name):
        return [dict(x) for x in self.meta.values() if x["name"]==name]

    def folder(self, fid):
        return dict(self.meta[fid])

    def upload(self, path, target):
        fid="uploaded-file"
        content=path.read_bytes()
        self.payload[fid]=content
        self.meta[fid]={
            "id":fid,"name":path.name,"size":str(len(content)),
            "md5Checksum":hashlib.md5(content).hexdigest(),
            "parents":[target],"shared":False,"permissions":self._owner()
        }
        self.calls.append(("UPLOAD",fid,target))
        return dict(self.meta[fid])

    def move(self, fid, old, new):
        assert self.meta[fid]["parents"]==[old]
        self.meta[fid]["parents"]=[new]
        self.calls.append(("MOVE",fid,old,new))
        return dict(self.meta[fid])

    def get(self, url, *, params, stream, timeout):
        fid=url.split("/")[-1]
        source=self.payload[fid]
        if self.tamper_download:
            source=source.replace(b"synthetic",b"altered!!")
        self.calls.append(("DOWNLOAD",fid))
        return Reply(200,chunks=(source,))

    def delete(self, url, *, timeout):
        fid=url.split("/")[-1]
        self.deleted.append(fid)
        self.calls.append(("DELETE",fid))
        if self.fail_delete:
            return Reply(503)
        self.meta.pop(fid,None)
        self.payload.pop(fid,None)
        return Reply(204)


class LiveSmokeSyntheticTests(unittest.TestCase):
    def run_fake(self, client):
        with tempfile.TemporaryDirectory() as root:
            with patch("tools.drive_live_smoke.DriveAPI",return_value=client):
                return live_smoke("synthetic-access-only",local_directory=Path(root))

    def test_full_live_flow_upload_repeat_repair_hash_cleanup(self):
        client=MockDriveREST()
        report=self.run_fake(client)
        self.assertEqual(report["status"],"P8C_LOCAL_ADAPTER_REAL_API_PASS")
        self.assertTrue(report["independent_cloud_sha256"])
        self.assertTrue(report["original_id_preserved"])
        self.assertTrue(report["owner_only"])
        self.assertEqual(report["generic_verify"],"PRIVATE_DELIVERY_PASS")
        self.assertTrue(report["temporary_cloud_objects_deleted"])
        self.assertEqual(len([c for c in client.calls if c[0]=="UPLOAD"]),1)
        self.assertEqual(len([c for c in client.calls if c[0]=="MOVE"]),2)
        self.assertEqual(len([c for c in client.calls if c[0]=="DOWNLOAD"]),1)
        self.assertEqual(len(client.deleted),2)
        self.assertFalse(client.meta)

    def test_independent_cloud_byte_mismatch_fails(self):
        client=MockDriveREST(tamper_download=True)
        with self.assertRaisesRegex(PlacementError,"LIVE_CLOUD_SHA256_OR_BYTES_MISMATCH"):
            self.run_fake(client)
        self.assertEqual(len(client.deleted),2)

    def test_public_test_folder_is_rejected(self):
        client=MockDriveREST(public_folder=True)
        with self.assertRaisesRegex(PlacementError,"LIVE_TEST_FOLDER_ACL_NOT_OWNER_ONLY"):
            self.run_fake(client)
        self.assertEqual(len([x for x in client.calls if x[0]=="UPLOAD"]),0)
        self.assertEqual(len(client.deleted),1)

    def test_cleanup_failure_does_not_claim_live_pass(self):
        client=MockDriveREST(fail_delete=True)
        report=self.run_fake(client)
        self.assertEqual(report["status"],"P8C_REAL_API_SMOKE_CLEANUP_INCOMPLETE")
        self.assertFalse(report["temporary_cloud_objects_deleted"])
        self.assertEqual(len(report["cleanup_errors"]),2)


if __name__=="__main__":
    unittest.main()
