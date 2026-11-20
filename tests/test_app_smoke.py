"""Headless smoke test for the Tkinter shell.

Skipped automatically when Tk cannot open a display, so the suite still runs
in plain CI containers (or on a server without X).
"""

import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
except Exception:  # pragma: no cover - tkinter not built into this Python
    tk = None

from focusdeck.app import FocusDeckApp
from focusdeck.engine import Phase, PhaseCompleted, Settings
from focusdeck.store import Store


@unittest.skipIf(tk is None, "tkinter is not available")
class AppSmokeTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # no display
            self.skipTest(f"no display available: {exc}")
        self.root.withdraw()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "smoke.db")
        self.app = FocusDeckApp(self.root, self.store)

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def test_builds_all_tabs(self):
        tabs = [self.app.notebook.tab(t, "text") for t in self.app.notebook.tabs()]
        self.assertEqual(tabs, ["Timer", "Tasks", "History", "Settings"])
        self.assertEqual(self.app.timer_view.clock.cget("text"), "25:00")

    def test_timer_controls(self):
        self.app.toggle_timer()
        self.assertTrue(self.app.engine.running)
        self.assertEqual(self.app.timer_view.start_button.cget("text"), "Pause")
        self.app.toggle_timer()
        self.assertFalse(self.app.engine.running)
        self.app.reset_timer()
        self.assertEqual(self.app.engine.remaining_seconds, 1500)

    def test_tasks_flow(self):
        task = self.app.add_task("Ship the release")
        self.assertEqual(self.app.store.tasks()[0].title, "Ship the release")
        self.assertIn("Ship the release", self.app.timer_view.task_combo.cget("values"))

        self.app.set_active_task(task.id)
        self.assertEqual(self.app.active_task_id, task.id)

        self.app.set_task_done(task.id, True)
        self.assertTrue(self.app.store.tasks()[0].done)

        self.app.delete_task(task.id)
        self.assertIsNone(self.app.active_task_id)
        self.assertEqual(self.app.store.tasks(), [])

    def test_completed_focus_session_is_recorded(self):
        self.app._handle_completion(PhaseCompleted(Phase.FOCUS, 1500))
        rows = self.app.store.recent_sessions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["duration_seconds"], 1500)
        self.assertIn("1 session", self.app.timer_view.summary.cget("text"))

    def test_settings_are_applied_and_persisted(self):
        self.app.save_settings(Settings(focus_minutes=50, daily_goal_minutes=200))
        self.assertEqual(self.app.engine.total_seconds, 3000)
        self.assertEqual(self.app.store.load_settings()["focus_minutes"], 50)
        self.assertIn("200 min", self.app.timer_view.summary.cget("text"))

    def test_history_view_renders(self):
        self.app.store.record_session(Phase.FOCUS, 1500)
        self.app.history_view.reload()
        self.assertGreaterEqual(len(self.app.history_view.tree.get_children()), 1)


if __name__ == "__main__":
    unittest.main()
