from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gadget_msc_printer.auth import AuthStore, SessionStore


class AuthTests(unittest.TestCase):
    def test_initial_password_and_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(directory)
            initial = store.ensure_admin()
            self.assertIsNotNone(initial)
            self.assertTrue((Path(directory) / "auth" / "initial_password.txt").exists())
            ok, must_change = store.verify("admin", str(initial))
            self.assertTrue(ok)
            self.assertTrue(must_change)
            store.set_password("new-password-123")
            ok, must_change = store.verify("admin", "new-password-123")
            self.assertTrue(ok)
            self.assertFalse(must_change)
            self.assertFalse((Path(directory) / "auth" / "initial_password.txt").exists())

    def test_sessions_have_independent_csrf_tokens(self) -> None:
        sessions = SessionStore(1)
        first = sessions.create("first")
        second = sessions.create("second")
        self.assertNotEqual(first.token, second.token)
        self.assertNotEqual(first.csrf, second.csrf)
        self.assertEqual(first.username, "first")
        self.assertIsNotNone(sessions.get(first.token))


if __name__ == "__main__":
    unittest.main()
