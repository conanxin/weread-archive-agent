"""Offline structural safety tests for Windows Remote recovery.

These checks are NOT a substitute for actually running PowerShell on Windows.
"""
from pathlib import Path
import unittest

PS = Path(__file__).resolve().parents[1] / "tools" / "windows" / "dc_remote_recover.ps1"


class RecoverySafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PS.read_text(encoding="utf-8")

    def test_read_only_default_and_explicit_apply(self):
        self.assertIn("[string]$Mode = 'Diagnose'", self.text)
        self.assertIn("[switch]$Apply", self.text)
        self.assertIn("if ($Mode -eq 'Diagnose')", self.text)
        self.assertIn("DRY_RUN_NEEDS_EXPLICIT_APPLY", self.text)

    def test_fail_closed_when_agent_or_task_is_not_ready(self):
        for value in (
            "SKIP_REMOTE_PROCESS_EXISTS", "SKIP_LEGACY_NPX_PROCESS_PRESENT",
            "SKIP_TASK_DISABLED", "SKIP_TASK_NOT_READY",
            "SKIP_PINNED_RUNTIME_MISSING",
        ):
            self.assertIn(value, self.text)

    def test_existing_watchdog_fails_closed_without_competing_restart(self):
        self.assertIn("ExistingWatchdogEnabled", self.text)
        self.assertIn("ExistingWatchdogLastResult", self.text)
        self.assertIn("SKIP_EXISTING_WATCHDOG_MANAGES_RECOVERY", self.text)
        guard = self.text.index("elseif ($summary.ExistingWatchdogEnabled)")
        start = self.text.index("Start-ScheduledTask -TaskName $TaskName")
        self.assertLess(guard, start)

    def test_auth_confirmation_and_throttle(self):
        self.assertIn("SKIP_LOCAL_SESSION_MISSING_USER_AUTH_REQUIRED", self.text)
        self.assertIn("SKIP_AUTH_INDICATION_REQUIRES_HUMAN_REVIEW", self.text)
        self.assertIn("SKIP_HOURLY_RETRY_BUDGET", self.text)
        self.assertIn("SKIP_BACKOFF_INTERVAL", self.text)
        self.assertIn("Save-ThrottleState", self.text)

    def test_never_kills_or_clears_credentials(self):
        for dangerous in (
            "Stop-Process", "--logout", "Remove-Item -LiteralPath $session",
            "Remove-Item -LiteralPath $entry",
            "Unregister-ScheduledTask", "Set-ScheduledTask",
        ):
            self.assertNotIn(dangerous, self.text)
        self.assertIn("CredentialContentsRead = $false", self.text)
        self.assertIn("START_REQUESTED_NOT_YET_VERIFIED", self.text)


if __name__ == "__main__":
    unittest.main()
