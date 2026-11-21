import tempfile
import unittest
from pathlib import Path

from streamstudy.updates import (
    UpdateStatus,
    check_for_update,
    update_instructions,
    versions_differ,
)

REMOTE_SHA = "b" * 40
LOCAL_SHA = "a" * 40


class FakeClient:
    def __init__(self, version: str = "0.2.0", fail: bool = False) -> None:
        self.version = version
        self.fail = fail

    def get_json(self, url, params=None):
        if self.fail:
            raise RuntimeError("offline")
        return {
            "sha": REMOTE_SHA,
            "commit": {"committer": {"date": "2026-11-21T12:00:00Z"}},
            "html_url": "https://github.com/llascari/RFD_LL_StreamStudy/commit/bbb",
        }

    def get_text(self, url, params=None):
        if self.fail:
            raise RuntimeError("offline")
        return self.version + "\n"


class VersionTest(unittest.TestCase):
    def test_numeric_versions(self):
        self.assertTrue(versions_differ("0.1.0", "0.2.0"))
        self.assertFalse(versions_differ("0.2.0", "0.2.0"))
        self.assertFalse(versions_differ("0.3.0", "0.2.0"))

    def test_non_numeric_falls_back_to_equality(self):
        self.assertTrue(versions_differ("main", "dev"))
        self.assertFalse(versions_differ("main", "main"))


class ArchiveCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "VERSION").write_text("0.1.0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_available(self):
        status = check_for_update(self.root, FakeClient("0.2.0"))
        self.assertTrue(status.available)
        self.assertEqual(status.method, "archive")
        self.assertEqual(status.local, "0.1.0")
        self.assertEqual(status.remote, "0.2.0")
        instructions = update_instructions(status, self.root)
        self.assertIn("archive/refs/heads/main.zip", instructions)
        self.assertIn("settings live outside", instructions)

    def test_up_to_date(self):
        status = check_for_update(self.root, FakeClient("0.1.0"))
        self.assertFalse(status.available)

    def test_offline_is_unknown(self):
        status = check_for_update(self.root, FakeClient(fail=True))
        self.assertIsNone(status.available)
        self.assertTrue(status.error)


class GitCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        (self.root / "VERSION").write_text("0.2.0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_comparison(self):
        status = check_for_update(
            self.root, FakeClient(), sha_reader=lambda _root: LOCAL_SHA
        )
        self.assertTrue(status.available)
        self.assertEqual(status.method, "git")
        self.assertIn("git pull", update_instructions(status, self.root))

        same = check_for_update(
            self.root, FakeClient(), sha_reader=lambda _root: REMOTE_SHA
        )
        self.assertFalse(same.available)

    def test_missing_git_revision_is_unknown(self):
        status = check_for_update(self.root, FakeClient(), sha_reader=lambda _root: None)
        self.assertFalse(status.available)
        self.assertEqual(status.local, "")


if __name__ == "__main__":
    unittest.main()
