"""The history tab: recent sessions, a 7-day chart and summary numbers."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import ttk

from .theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    MUTED,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    font_family,
)

_PHASE_LABELS = {
    "focus": "Focus",
    "short_break": "Short break",
    "long_break": "Long break",
}


class HistoryView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(26, 20))
        self.app = app
        self._series: list[tuple[date, int]] = []
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="History", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Completed focus sessions, newest first.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        cards = ttk.Frame(self)
        cards.grid(row=2, column=0, sticky="ew")
        self.today_var = tk.StringVar(value="0 min")
        self.week_var = tk.StringVar(value="0 min")
        self.total_var = tk.StringVar(value="0 min")
        self._stat_card(cards, 0, "Today", self.today_var)
        self._stat_card(cards, 1, "Last 7 days", self.week_var)
        self._stat_card(cards, 2, "All time", self.total_var)

        self.chart = tk.Canvas(
            self, height=170, bg=SURFACE, highlightthickness=0, bd=0
        )
        self.chart.grid(row=3, column=0, sticky="ew", pady=(14, 6))
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())

        detail = ttk.Frame(self)
        detail.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(4, weight=1)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)

        columns = ("when", "phase", "minutes", "task")
        self.tree = ttk.Treeview(detail, columns=columns, show="headings")
        headings = {
            "when": ("When", 150, "w"),
            "phase": ("Phase", 110, "w"),
            "minutes": ("Minutes", 80, "e"),
            "task": ("Task", 240, "w"),
        }
        for key, (label, width, anchor) in headings.items():
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "task"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(detail, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

    def _stat_card(
        self, parent: ttk.Frame, column: int, caption: str, var: tk.StringVar
    ) -> None:
        parent.columnconfigure(column, weight=1)
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.grid(row=0, column=column, sticky="ew", padx=(0, 10))
        ttk.Label(card, text=caption, style="Card.TLabel", foreground=MUTED).pack(
            anchor="w"
        )
        ttk.Label(
            card,
            textvariable=var,
            style="Card.TLabel",
            font=(font_family(self), 16, "bold"),
        ).pack(anchor="w", pady=(2, 0))

    # -- data ----------------------------------------------------------
    def reload(self) -> None:
        store = self.app.store
        today = date.today()
        self._series = store.focus_seconds_by_day(7, today=today)

        today_seconds = self._series[-1][1] if self._series else 0
        week_seconds = sum(seconds for _, seconds in self._series)
        total_seconds = store.total_focus_seconds()

        sessions_today = store.focus_sessions_on(today)
        self.today_var.set(f"{today_seconds // 60} min")
        self.week_var.set(f"{week_seconds // 60} min")
        self.total_var.set(_format_long(total_seconds))
        self._draw_chart()
        self._fill_table(sessions_today)

    def _fill_table(self, sessions_today: int) -> None:
        self.tree.delete(*self.tree.get_children())
        for session in self.app.store.recent_sessions(100):
            try:
                started = datetime.fromisoformat(session["started_at"])
            except (TypeError, ValueError):
                continue
            minutes = int(round(session["duration_seconds"] / 60))
            self.tree.insert(
                "",
                "end",
                values=(
                    started.strftime("%b %d, %H:%M"),
                    _PHASE_LABELS.get(session["phase"], session["phase"]),
                    minutes,
                    session["task_title"] or "\u2014",
                ),
            )
        if sessions_today == 0:
            self.tree.insert(
                "", "end", values=("\u2014", "No sessions yet today", "", "")
            )

    # -- chart ---------------------------------------------------------
    def _draw_chart(self) -> None:
        canvas = self.chart
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 60 or height < 60:
            return
        if not self._series:
            return

        family = font_family(self)
        pad_l, pad_r, pad_t, pad_b = 44, 16, 18, 28
        plot_w = max(10, width - pad_l - pad_r)
        plot_h = max(10, height - pad_t - pad_b)
        base_y = height - pad_b
        peak = max([seconds for _, seconds in self._series] + [60])

        goal_seconds = self.app.settings.daily_goal_minutes * 60
        if goal_seconds <= peak:
            goal_y = base_y - goal_seconds / peak * plot_h
            canvas.create_line(
                pad_l, goal_y, width - pad_r, goal_y, fill=BORDER, dash=(4, 4)
            )
            canvas.create_text(
                pad_l - 6,
                goal_y,
                text="goal",
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )

        canvas.create_line(pad_l, base_y, width - pad_r, base_y, fill=BORDER)
        slot = plot_w / len(self._series)
        bar_w = min(44.0, slot * 0.5)
        today = date.today()
        for index, (day, seconds) in enumerate(self._series):
            x_center = pad_l + slot * index + slot / 2
            x0 = x_center - bar_w / 2
            bar_h = seconds / peak * plot_h
            fill = ACCENT_HOVER if day == today else ACCENT
            if bar_h > 0:
                canvas.create_rectangle(
                    x0, base_y - bar_h, x0 + bar_w, base_y, fill=fill, outline=""
                )
            canvas.create_text(
                x_center,
                base_y + 14,
                text=day.strftime("%a"),
                fill=TEXT if day == today else MUTED,
                font=(family, 9, "bold" if day == today else "normal"),
            )
            if seconds:
                canvas.create_text(
                    x_center,
                    base_y - bar_h - 10,
                    text=f"{seconds // 60}",
                    fill=TEXT,
                    font=(family, 9),
                )


def _format_long(seconds: int) -> str:
    minutes = seconds // 60
    hours, rest = divmod(minutes, 60)
    if hours:
        return f"{hours} h {rest} min"
    return f"{rest} min"
