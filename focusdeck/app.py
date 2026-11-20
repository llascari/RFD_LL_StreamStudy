"""Application shell: wires the engine, the store and the Tk views together."""

from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk

from .engine import Phase, PhaseCompleted, PomodoroEngine, Settings
from .store import Store, Task
from .ui.history_view import HistoryView
from .ui.settings_view import SettingsView
from .ui.tasks_view import TasksView
from .ui.theme import apply_theme
from .ui.timer_view import TimerView

APP_NAME = "FocusDeck"


class FocusDeckApp:
    """Controller for the main window; the views only talk to this object."""

    def __init__(self, root: tk.Tk, store: Store) -> None:
        self.root = root
        self.store = store
        self.settings = Settings.from_dict(store.load_settings())
        self.engine = PomodoroEngine(self.settings)
        self.active_task_id: int | None = None
        self._last_tick = time.monotonic()
        self._closed = False

        self._build_window()
        self.refresh_all()
        self.root.after(100, self._tick)

    # -- window --------------------------------------------------------
    def _build_window(self) -> None:
        self.root.title(APP_NAME)
        self.root.geometry("780x660")
        self.root.minsize(680, 600)
        apply_theme(self.root)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        self.timer_view = TimerView(self.notebook, self)
        self.tasks_view = TasksView(self.notebook, self)
        self.history_view = HistoryView(self.notebook, self)
        self.settings_view = SettingsView(self.notebook, self)

        self.notebook.add(self.timer_view, text="Timer")
        self.notebook.add(self.tasks_view, text="Tasks")
        self.notebook.add(self.history_view, text="History")
        self.notebook.add(self.settings_view, text="Settings")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.root.bind("<space>", self._on_space)
        self.root.bind("<Control-n>", lambda _e: self.notebook.select(self.tasks_view))
        self.root.bind("<Control-comma>", lambda _e: self.notebook.select(self.settings_view))
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.engine.pause()
        self.store.close()
        self.root.destroy()

    # -- refresh -------------------------------------------------------
    def refresh_all(self) -> None:
        self.refresh_tasks()
        self.timer_view.refresh()
        self.refresh_summary()
        self.history_view.reload()
        self.settings_view.load(self.settings)

    def refresh_tasks(self) -> None:
        tasks = self.store.tasks()
        if self.active_task_id is not None and not any(
            task.id == self.active_task_id for task in tasks
        ):
            self.active_task_id = None
        self.timer_view.set_tasks(tasks, self.active_task_id)
        self.tasks_view.set_tasks(tasks)

    def refresh_summary(self) -> None:
        today = datetime.now().date()
        seconds = self.store.focus_seconds_by_day(1, today=today)[0][1]
        sessions = self.store.focus_sessions_on(today)
        self.timer_view.set_summary(
            f"{seconds // 60} min focused today  \u00b7  {sessions} session"
            f"{'' if sessions == 1 else 's'}  \u00b7  goal {self.settings.daily_goal_minutes} min"
        )

    # -- timer actions -------------------------------------------------
    def toggle_timer(self) -> None:
        self.engine.toggle()
        self._last_tick = time.monotonic()
        if self.engine.running:
            self.timer_view.set_status(self._running_message())
        else:
            self.timer_view.set_status("Paused.")
        self.timer_view.refresh()

    def reset_timer(self) -> None:
        self.engine.reset()
        minutes = self.engine.total_seconds // 60
        self.timer_view.set_status(f"Timer reset to {minutes} minutes.")
        self.timer_view.refresh()

    def skip_phase(self) -> None:
        self.engine.skip()
        self.timer_view.set_status(f"Skipped ahead: {self.engine.phase.label}.")
        self.timer_view.refresh()

    def _running_message(self) -> str:
        if self.engine.phase is Phase.FOCUS:
            return "Focusing. One thing at a time."
        return f"{self.engine.phase.label}. Step away from the screen."

    # -- tasks ---------------------------------------------------------
    def add_task(self, title: str) -> Task:
        task = self.store.add_task(title)
        self.refresh_tasks()
        return task

    def set_task_done(self, task_id: int, done: bool) -> None:
        self.store.set_task_done(task_id, done)
        self.refresh_tasks()

    def delete_task(self, task_id: int) -> None:
        self.store.delete_task(task_id)
        if self.active_task_id == task_id:
            self.active_task_id = None
        self.refresh_tasks()

    def set_active_task(self, task_id: int | None) -> None:
        self.active_task_id = task_id
        self.timer_view.set_tasks(self.store.tasks(), self.active_task_id)
        if task_id is None:
            self.timer_view.set_status("No task selected. Pick one on the Timer tab.")
        else:
            task = next((t for t in self.store.tasks() if t.id == task_id), None)
            if task is not None:
                self.timer_view.set_status(f"Active task: {task.title}", tone="accent")

    # -- settings ------------------------------------------------------
    def save_settings(self, settings: Settings) -> None:
        self.settings = settings.validated()
        self.engine.apply_settings(self.settings)
        self.store.save_settings(self.settings.to_dict())
        self.settings_view.load(self.settings)
        self.refresh_summary()
        self.timer_view.refresh()
        self.timer_view.set_status("Settings saved.", tone="success")

    # -- tabs & keys ---------------------------------------------------
    def show_timer(self) -> None:
        self.notebook.select(self.timer_view)

    def show_tasks(self) -> None:
        self.notebook.select(self.tasks_view)
        self.tasks_view.focus_input()

    def _on_tab_changed(self, _event: tk.Event) -> None:
        if self.notebook.select() == str(self.history_view):
            self.history_view.reload()

    def _on_space(self, event: tk.Event) -> str | None:
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return None
        self.toggle_timer()
        return "break"

    # -- the clock -----------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        delta = now - self._last_tick
        self._last_tick = now
        if delta > 60:
            # The machine was probably asleep; don't fast-forward the timer.
            delta = 0.0
        if self.engine.running:
            for completed in self.engine.advance(delta):
                self._handle_completion(completed)
        self.timer_view.refresh()
        self.root.after(100, self._tick)

    def _handle_completion(self, completed: PhaseCompleted) -> None:
        if completed.phase is Phase.FOCUS:
            started = datetime.now() - timedelta(seconds=completed.duration_seconds)
            self.store.record_session(
                Phase.FOCUS,
                completed.duration_seconds,
                task_id=self.active_task_id,
                started_at=started,
            )
            self.refresh_summary()
            self.history_view.reload()
            self.timer_view.set_status(
                f"Focus session logged ({completed.duration_seconds // 60} min). "
                f"{self.engine.phase.label} is up next.",
                tone="success",
            )
        else:
            self.timer_view.set_status(
                f"{completed.phase.label} is over \u2014 back to focus.", tone="success"
            )
        try:
            self.root.bell()
        except tk.TclError:  # pragma: no cover - no bell on some systems
            pass


def run(db_path: str | None = None) -> int:
    """Create the window and run the Tk main loop."""
    root = tk.Tk()
    store = Store(db_path)
    try:
        FocusDeckApp(root, store)
        root.mainloop()
    finally:
        store.close()
    return 0
