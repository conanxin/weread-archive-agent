"""Personal Google Drive OAuth bootstrap for the explicit-parent upload adapter.

The OAuth desktop client JSON comes from the user's own Google Cloud project.
Refreshable user credentials stay under ignored .local and are never printed.
No network calls or browser launch occur unless explicit --authorize is passed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


class OAuthNotReady(RuntimeError):
    """A local user-authorized OAuth step is required."""


def _google_clients():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise OAuthNotReady(
            "OAUTH_LIBRARY_NOT_INSTALLED: pip install google-auth-oauthlib"
        ) from exc
    return Credentials, Request, InstalledAppFlow


def _save_token(cache: Path, credentials) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    pending = cache.with_suffix(cache.suffix + ".writing")
    if pending.exists():
        raise OAuthNotReady("PRIOR_OAUTH_CACHE_WRITE_INCOMPLETE")
    try:
        pending.write_text(credentials.to_json(), encoding="utf-8")
        # Best effort file owner restriction, particularly useful on WSL/Linux.
        if os.name != "nt":
            os.chmod(pending, 0o600)
        os.replace(pending, cache)
    finally:
        pending.unlink(missing_ok=True)


def get_access_token(*, token_cache: Path, client_json: Path | None = None,
                     authorize: bool = False) -> str:
    """Return a real Drive-scope access token without ever printing its value.

    Reuse/refresh a user-approved token. If absent, fail closed unless
    --authorize is explicitly passed by a person able to use the local browser.
    """
    token_cache = Path(token_cache)
    client_json = Path(client_json) if client_json is not None else None
    Credentials, Request, InstalledAppFlow = _google_clients()
    creds = None
    if token_cache.is_file():
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_cache), scopes=[DRIVE_SCOPE]
            )
        except (OSError, ValueError, KeyError) as exc:
            raise OAuthNotReady("INVALID_OAUTH_TOKEN_CACHE") from exc
        if not creds.has_scopes([DRIVE_SCOPE]):
            raise OAuthNotReady("OAUTH_SCOPE_INSUFFICIENT")
        if creds.valid and creds.token:
            return creds.token
        if creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                if not authorize:
                    raise OAuthNotReady("OAUTH_REFRESH_FAILED") from exc
            else:
                if creds.valid and creds.token:
                    _save_token(token_cache, creds)
                    return creds.token
    if not authorize:
        raise OAuthNotReady(
            "GOOGLE_DRIVE_OAUTH_USER_APPROVAL_REQUIRED: provide "
            "--oauth-client-json and --authorize once"
        )
    if client_json is None or not client_json.is_file():
        raise OAuthNotReady("OAUTH_DESKTOP_CLIENT_JSON_MISSING")
    try:
        raw = json.loads(client_json.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise OAuthNotReady("INVALID_OAUTH_CLIENT_JSON") from exc
    if not isinstance(raw, dict) or "installed" not in raw:
        raise OAuthNotReady("OAUTH_CLIENT_MUST_BE_DESKTOP_APP")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_json), scopes=[DRIVE_SCOPE]
    )
    creds = flow.run_local_server(
        host="127.0.0.1", port=0, open_browser=True,
        access_type="offline", prompt="consent",
        success_message="Google Drive authorization complete. Return to the local terminal.",
    )
    if not creds or not creds.valid or not creds.token or not creds.has_scopes([DRIVE_SCOPE]):
        raise OAuthNotReady("OAUTH_BROWSER_APPROVAL_NOT_COMPLETED")
    _save_token(token_cache, creds)
    return creds.token


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit one-time Google Drive OAuth approval on local Windows"
    )
    parser.add_argument("--client-json", type=Path)
    parser.add_argument("--token-cache", type=Path,
                        default=Path(".local/google_drive_oauth_user.json"))
    parser.add_argument("--authorize", action="store_true",
                        help="Open browser for explicit user approval")
    args = parser.parse_args()
    token = get_access_token(token_cache=args.token_cache,
                             client_json=args.client_json,
                             authorize=args.authorize)
    if not token:
        raise OAuthNotReady("OAUTH_TOKEN_EMPTY")
    print(json.dumps({
        "status": "GOOGLE_DRIVE_OAUTH_READY",
        "scope": DRIVE_SCOPE,
        "cache_saved": args.token_cache.exists(),
        "token_displayed": False,
        "cloud_upload_executed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
