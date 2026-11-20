"""The timer tab: clock, controls and the active task selector."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..engine import Phase, format_seconds
from .theme import ACCENT, BG, MUTED, SUCCESS

_PHASE_STYLE = {
    Phase.FOCUS: "PhaseFocus.TLabel",
    Phase.SHORT_BREAK: "PhaseShort.TLabel",
    Phase.LONG_BREAK: "PhaseLong.TLabel",
}


class TimerView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(30, 16, 30, 18))
        self.app = app
        self._tasks: list = []
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.phase_label = ttk.Label(
            self, text="Focus", style="PhaseFocus.TLabel", anchor="center"
        )
        self.phase_label.grid(row=0, column=0, pady=(14, 0))

        self.clock = ttk.Label(self, text="25:00", style="Clock.TLabel", anchor="center")
        self.clock.grid(row=1, column=0, pady=(0, 4))

        self.progress = ttk.Progressbar(
            self, style="Timer.Horizontal.TProgressbar", maximum=1000, value=0
        )
        self.progress.grid(row=2, column=0, sticky="ew", padx=60, pady=(2, 20))

        controls = ttk.Frame(self)
        controls.grid(row=3, column=0)
        self.start_button = ttk.Button(
            controls, text="Start", style="Accent.TButton", command=self.app.toggle_timer
        )
        self.start_button.pack(side="left", padx=5)
        ttk.Button(controls, text="Reset", command=self.app.reset_timer).pack(
            side="left", padx=5
        )
        ttk.Button(controls, text="Skip", command=self.app.skip_phase).pack(
            side="left", padx=5
        )

        task_row = ttk.Frame(self)
        task_row.grid(row=4, column=0, sticky="ew", padx=60, pady=(26, 0))
        task_row.columnconfigure(1, weight=1)
        ttk.Label(task_row, text="Working on", style="Muted.TLabel").grid(
            row=0, column=0, padx=(0, 10)
        )
        self.task_combo = ttk.Combobox(
            task_row, state="readonly", values=["No task"], width=34
        )
        self.task_combo.grid(row=0, column=1, sticky="ew")
        self.task_combo.set("No task")
        self.task_combo.bind("<<ComboboxSelected>>", self._on_task_selected)

        self.summary = ttk.Label(self, text="", style="Muted.TLabel", anchor="center")
        self.summary.grid(row=5, column=0, pady=(20, 0))

        self.status = tk.Label(
            self,
            text="Press Start to begin your first focus session.",
            bg=BG,
            fg=MUTED,
            font=("TkDefaultFont", 10),
            wraplength=520,
            justify="center",
        )
        self.status.grid(row=6, column=0, pady=(8, 0))
        self.rowconfigure(7, weight=1)

    # -- external API --------------------------------------------------
    def refresh(self) -> None:
        engine = self.app.engine
        self.clock.configure(text=format_seconds(engine.remaining_seconds))
        self.phase_label.configure(
            text=engine.phase.label, style=_PHASE_STYLE[engine.phase]
        )
        self.progress.configure(value=int(engine.progress * 1000))
        self.start_button.configure(text="Pause" if engine.running else "Start")

    def set_tasks(self, tasks: list, active_id: int | None) -> None:
        self._tasks = list(tasks)
        titles = ["No task"] + [task.title for task in self._tasks]
        self.task_combo.configure(values=titles)
        match = next((t for t in self._tasks if t.id == active_id), None)
        self.task_combo.set(match.title if match else "No task")

    def set_summary(self, text: str) -> None:
        self.summary.configure(text=text)

    def set_status(self, text: str, tone: str = "muted") -> None:
        colors = {"muted": MUTED, "success": SUCCESS, "accent": ACCENT}
        self.status.configure(text=text, fg=colors.get(tone, MUTED))

    # -- events --------------------------------------------------------
    def _on_task_selected(self, _event: tk.Event | None = None) -> None:
        title = self.task_combo.get()
        if title == "No task":
            self.app.set_active_task(None)
            return
        for task in self._tasks:
            if task.title == title:
                self.app.set_active_task(task.id)
                return
        self.app.set_active_task(None)
