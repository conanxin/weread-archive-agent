"""Synthetic OAuth tests only: no Google account, browser, or real tokens."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.drive_oauth_bootstrap import (
    DRIVE_SCOPE, OAuthNotReady, get_access_token,
)


class MockCredentials:
    refreshed = 0
    def __init__(self, token="unit-test-token", valid=True, refresh_token="refresh",
                 allow_scope=True):
        self.token=token
        self.valid=valid
        self.refresh_token=refresh_token
        self.allow_scope=allow_scope

    @classmethod
    def from_authorized_user_file(cls, name, scopes):
        source=json.loads(Path(name).read_text(encoding="utf-8"))
        return cls(token=source.get("token"), valid=source.get("valid",False),
                   refresh_token=source.get("refresh_token"),
                   allow_scope=source.get("scope")==DRIVE_SCOPE)

    def has_scopes(self, requested):
        return self.allow_scope and requested==[DRIVE_SCOPE]

    def refresh(self, request):
        if self.refresh_token=="bad":
            raise RuntimeError("synthetic revoked refresh")
        type(self).refreshed+=1
        self.token="unit-test-refreshed"
        self.valid=True

    def to_json(self):
        return json.dumps({"token":self.token,"valid":self.valid,
                           "refresh_token":self.refresh_token,"scope":DRIVE_SCOPE})


class MockRequest:
    pass


class MockFlow:
    consent_calls=0

    @classmethod
    def from_client_secrets_file(cls, filename, scopes):
        assert Path(filename).is_file()
        assert scopes==[DRIVE_SCOPE]
        return cls()

    def run_local_server(self, **options):
        type(self).consent_calls+=1
        assert options.get("open_browser") is True
        assert options.get("host")=="127.0.0.1"
        return MockCredentials(token="unit-test-approved")


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache=Path(self.tmp.name)/"token.json"
        self.client=Path(self.tmp.name)/"client.json"
        self.client.write_text(json.dumps({"installed":{"client_id":"fake-local"}}))
        MockCredentials.refreshed=0
        MockFlow.consent_calls=0
        self.patch=patch(
            "tools.drive_oauth_bootstrap._google_clients",
            return_value=(MockCredentials,MockRequest,MockFlow)
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def store(self, token="saved", valid=True, refresh_token="refresh",
              scope=DRIVE_SCOPE):
        self.cache.write_text(json.dumps({
            "token":token, "valid":valid, "refresh_token":refresh_token,
            "scope":scope
        }),encoding="utf-8")

    def test_cached_valid_access_token_has_no_browser_or_network(self):
        self.store()
        token=get_access_token(token_cache=self.cache)
        self.assertEqual(token,"saved")
        self.assertEqual(MockCredentials.refreshed,0)
        self.assertEqual(MockFlow.consent_calls,0)

    def test_expired_token_refreshes_and_persists(self):
        self.store(token="expired",valid=False)
        value=get_access_token(token_cache=self.cache)
        self.assertEqual(value,"unit-test-refreshed")
        self.assertEqual(MockCredentials.refreshed,1)
        self.assertEqual(json.loads(self.cache.read_text())["token"],value)

    def test_no_token_without_user_approval_fails_closed(self):
        with self.assertRaisesRegex(OAuthNotReady,"USER_APPROVAL_REQUIRED"):
            get_access_token(token_cache=self.cache,client_json=self.client)
        self.assertEqual(MockFlow.consent_calls,0)

    def test_first_time_desktop_consent_requires_explicit_flag(self):
        token=get_access_token(token_cache=self.cache,client_json=self.client,
                               authorize=True)
        self.assertEqual(token,"unit-test-approved")
        self.assertEqual(MockFlow.consent_calls,1)
        self.assertEqual(json.loads(self.cache.read_text())["token"],token)

    def test_browser_approval_requires_desktop_client_json(self):
        with self.assertRaisesRegex(OAuthNotReady,"OAUTH_DESKTOP_CLIENT_JSON_MISSING"):
            get_access_token(token_cache=self.cache,authorize=True)
        self.client.write_text(json.dumps({"web":{"client_id":"fake"}}))
        with self.assertRaisesRegex(OAuthNotReady,"OAUTH_CLIENT_MUST_BE_DESKTOP_APP"):
            get_access_token(token_cache=self.cache,client_json=self.client,
                             authorize=True)

    def test_invalid_cache_is_not_overwritten(self):
        self.cache.write_text("not-json",encoding="utf-8")
        with self.assertRaisesRegex(OAuthNotReady,"INVALID_OAUTH_TOKEN_CACHE"):
            get_access_token(token_cache=self.cache,client_json=self.client,
                             authorize=True)
        self.assertEqual(self.cache.read_text(),"not-json")

    def test_insufficient_scope_blocks_without_browser(self):
        self.store(scope="https://www.googleapis.com/auth/drive.file")
        with self.assertRaisesRegex(OAuthNotReady,"OAUTH_SCOPE_INSUFFICIENT"):
            get_access_token(token_cache=self.cache,client_json=self.client,
                             authorize=True)
        self.assertEqual(MockFlow.consent_calls,0)

    def test_revoked_token_blocks_unattended_refresh(self):
        self.store(valid=False,refresh_token="bad")
        with self.assertRaisesRegex(OAuthNotReady,"OAUTH_REFRESH_FAILED"):
            get_access_token(token_cache=self.cache)
        self.assertEqual(MockFlow.consent_calls,0)

    def test_revoked_token_can_request_fresh_manual_consent(self):
        self.store(valid=False,refresh_token="bad")
        value=get_access_token(token_cache=self.cache,client_json=self.client,
                               authorize=True)
        self.assertEqual(value,"unit-test-approved")
        self.assertEqual(MockFlow.consent_calls,1)


if __name__=="__main__":
    unittest.main()
