"""Tests for server/crash_notify.py"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server.crash_notify as cn


def _make_mock_response(status=200):
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestNotifyCrashRequest(unittest.TestCase):
    """Verify the HTTP request shape sent by notify_crash."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig_db = cn.DB_PATH
        cn.DB_PATH = self.tmp.name

    def tearDown(self):
        cn.DB_PATH = self._orig_db
        os.unlink(self.tmp.name)

    def _captured_request(self, failure_count, last_error=None):
        """Call notify_crash and return the parsed JSON body sent to ntfy."""
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _make_mock_response(200)
            cn.notify_crash("basecamp-logger", failure_count, last_error)
            call_args = mock_open.call_args[0][0]
            return json.loads(call_args.data.decode())

    def test_first_failure_default_priority(self):
        body = self._captured_request(1)
        self.assertEqual(body["priority"], "default")
        self.assertIn("warning", body["tags"])
        self.assertEqual(body["title"], "Basecamp: basecamp-logger crashed")
        self.assertIn("1 time(s)", body["message"])

    def test_third_failure_high_priority(self):
        body = self._captured_request(3)
        self.assertEqual(body["priority"], "high")
        self.assertIn("rotating_light", body["tags"])
        self.assertIn("3 time(s)", body["message"])

    def test_last_error_appended_and_truncated(self):
        long_error = "x" * 300
        body = self._captured_request(1, last_error=long_error)
        # truncated to 200 chars
        self.assertIn("x" * 200, body["message"])
        self.assertNotIn("x" * 201, body["message"])

    def test_returns_true_on_success(self):
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _make_mock_response(200)
            result = cn.notify_crash("basecamp-logger", 1)
        self.assertTrue(result)

    def test_returns_false_on_network_error(self):
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = ConnectionError("unreachable")
            result = cn.notify_crash("basecamp-logger", 1)
        self.assertFalse(result)

    def test_never_raises_on_network_error(self):
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = OSError("network failure")
            try:
                cn.notify_crash("basecamp-logger", 1)
            except Exception as exc:
                self.fail(f"notify_crash raised unexpectedly: {exc}")


class TestFailureCountDB(unittest.TestCase):
    """Verify failure count persistence and date-based reset."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig_db = cn.DB_PATH
        cn.DB_PATH = self.tmp.name

    def tearDown(self):
        cn.DB_PATH = self._orig_db
        os.unlink(self.tmp.name)

    def _call_notify(self, failure_count=1):
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _make_mock_response(200)
            cn.notify_crash("svc", failure_count)

    def test_count_increments_across_two_calls_same_date(self):
        self._call_notify(1)
        self.assertEqual(cn._get_failure_count("svc"), 1)
        self._call_notify(2)
        self.assertEqual(cn._get_failure_count("svc"), 2)

    def test_count_resets_on_new_date(self):
        with patch("server.crash_notify.date") as mock_date:
            mock_date.today.return_value = __import__("datetime").date(2026, 6, 9)
            self._call_notify(1)

        with patch("server.crash_notify.date") as mock_date:
            mock_date.today.return_value = __import__("datetime").date(2026, 6, 10)
            count = cn._get_failure_count("svc")
        self.assertEqual(count, 0)

    def test_zero_count_for_unseen_daemon(self):
        self.assertEqual(cn._get_failure_count("never-failed"), 0)


class TestNotifyRecovery(unittest.TestCase):
    """Verify notify_recovery behaviour."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig_db = cn.DB_PATH
        cn.DB_PATH = self.tmp.name

    def tearDown(self):
        cn.DB_PATH = self._orig_db
        os.unlink(self.tmp.name)

    def _seed_failure(self, daemon_name, count):
        """Insert a failure record directly into the DB."""
        import sqlite3
        from datetime import date
        conn = sqlite3.connect(self.tmp.name)
        cn._ensure_table(conn)
        today = date.today().isoformat()
        conn.execute(
            """INSERT INTO daemon_failures (daemon_name, date, failure_count)
               VALUES (?, ?, ?)
               ON CONFLICT(daemon_name, date) DO UPDATE SET failure_count=excluded.failure_count""",
            (daemon_name, today, count),
        )
        conn.commit()
        conn.close()

    def test_sends_notification_when_failures_exist(self):
        self._seed_failure("svc", 2)
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _make_mock_response(200)
            result = cn.notify_recovery("svc")
            self.assertTrue(result)
            self.assertTrue(mock_open.called)

    def test_skips_notification_when_no_failures(self):
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            result = cn.notify_recovery("svc")
        self.assertFalse(result)
        self.assertFalse(mock_open.called)

    def test_returns_false_silently_on_network_error(self):
        self._seed_failure("svc", 1)
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = OSError("network failure")
            try:
                result = cn.notify_recovery("svc")
            except Exception as exc:
                self.fail(f"notify_recovery raised unexpectedly: {exc}")
        self.assertFalse(result)

    def test_recovery_notification_is_low_priority(self):
        self._seed_failure("svc", 1)
        with patch("server.crash_notify.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _make_mock_response(200)
            cn.notify_recovery("svc")
            call_args = mock_open.call_args[0][0]
            body = json.loads(call_args.data.decode())
        self.assertEqual(body["priority"], "low")


if __name__ == "__main__":
    unittest.main()
