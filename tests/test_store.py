import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from focusdeck.engine import Phase
from focusdeck.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "focusdeck.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_creates_missing_parent_folder(self):
        self.assertTrue(self.path.exists())

    def test_task_lifecycle(self):
        task = self.store.add_task("  Write the report  ")
        self.assertEqual(task.title, "Write the report")
        self.assertFalse(task.done)
        self.assertEqual([t.id for t in self.store.tasks()], [task.id])

        self.store.set_task_done(task.id, True)
        loaded = self.store.tasks()
        self.assertTrue(loaded[0].done)
        self.assertEqual(self.store.tasks(include_done=False), [])

        self.store.delete_task(task.id)
        self.assertEqual(self.store.tasks(), [])

    def test_empty_task_title_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_task("   ")

    def test_daily_totals_are_zero_filled(self):
        today = date(2026, 5, 4)
        task = self.store.add_task("Deep work")
        self.store.record_session(
            Phase.FOCUS, 1500, task.id, datetime(2026, 5, 4, 9, 0)
        )
        self.store.record_session(Phase.FOCUS, 900, None, datetime(2026, 5, 3, 21, 0))
        self.store.record_session(
            Phase.SHORT_BREAK, 600, None, datetime(2026, 5, 4, 9, 30)
        )

        series = self.store.focus_seconds_by_day(7, today=today)
        self.assertEqual(len(series), 7)
        self.assertEqual(series[-1], (today, 1500))
        self.assertEqual(series[-2], (date(2026, 5, 3), 900))
        self.assertEqual(series[0][1], 0)

        self.assertEqual(self.store.focus_sessions_on(today), 1)
        self.assertEqual(self.store.total_focus_seconds(), 2400)

    def test_recent_sessions_include_task_title(self):
        task = self.store.add_task("Read paper")
        self.store.record_session(
            Phase.FOCUS, 600, task.id, datetime(2026, 5, 4, 9, 0)
        )
        rows = self.store.recent_sessions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_title"], "Read paper")
        self.assertEqual(rows[0]["phase"], "focus")
        self.assertEqual(rows[0]["duration_seconds"], 600)

    def test_deleting_a_task_keeps_its_sessions(self):
        task = self.store.add_task("Temporary")
        self.store.record_session(Phase.FOCUS, 600, task.id)
        self.store.delete_task(task.id)
        rows = self.store.recent_sessions()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["task_title"])

    def test_settings_roundtrip(self):
        self.assertEqual(self.store.load_settings(), {})
        self.store.save_settings({"focus_minutes": 45})
        self.assertEqual(self.store.load_settings(), {"focus_minutes": 45})
        self.store.save_settings({"focus_minutes": 30, "auto_start_focus": True})
        self.assertEqual(
            self.store.load_settings(),
            {"focus_minutes": 30, "auto_start_focus": True},
        )


if __name__ == "__main__":
    unittest.main()
