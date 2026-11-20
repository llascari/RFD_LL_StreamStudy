"""The settings tab: timer lengths, cycle length and automation."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..engine import Settings
from .theme import font_family


class SettingsView(ttk.Frame):
    FIELDS = (
        ("focus_minutes", "Focus length (minutes)", 1, 180),
        ("short_break_minutes", "Short break (minutes)", 1, 60),
        ("long_break_minutes", "Long break (minutes)", 1, 120),
        ("sessions_until_long_break", "Focus sessions before a long break", 1, 12),
        ("daily_goal_minutes", "Daily focus goal (minutes)", 15, 960),
    )

    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(26, 20))
        self.app = app
        self.vars: dict[str, tk.StringVar] = {
            key: tk.StringVar(value="") for key, *_ in self.FIELDS
        }
        self.auto_breaks = tk.BooleanVar(value=True)
        self.auto_focus = tk.BooleanVar(value=False)
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="Settings", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="A running timer keeps its elapsed time; new lengths apply to the next phase.",
            style="Muted.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        form = ttk.Frame(self)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        for row, (key, label, low, high) in enumerate(self.FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=6)
            ttk.Spinbox(
                form,
                from_=low,
                to=high,
                textvariable=self.vars[key],
                width=7,
                justify="right",
            ).grid(row=row, column=1, sticky="e", pady=6)

        checks = ttk.Frame(self)
        checks.grid(row=3, column=0, sticky="w", pady=(18, 0))
        ttk.Checkbutton(
            checks, text="Start breaks automatically", variable=self.auto_breaks
        ).pack(anchor="w")
        ttk.Checkbutton(
            checks, text="Start the next focus session automatically", variable=self.auto_focus
        ).pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky="w", pady=(24, 0))
        ttk.Button(
            actions, text="Save settings", style="Accent.TButton", command=self._save
        ).pack(side="left")
        ttk.Button(actions, text="Restore defaults", command=self._defaults).pack(
            side="left", padx=8
        )

        ttk.Label(
            self,
            text=f"Data file: {self.app.store.path}",
            style="Muted.TLabel",
            wraplength=560,
            justify="left",
            font=(font_family(self), 9),
        ).grid(row=5, column=0, sticky="w", pady=(28, 0))
        self.rowconfigure(6, weight=1)

    # -- external API --------------------------------------------------
    def load(self, settings: Settings) -> None:
        for key, *_ in self.FIELDS:
            self.vars[key].set(str(getattr(settings, key)))
        self.auto_breaks.set(settings.auto_start_breaks)
        self.auto_focus.set(settings.auto_start_focus)

    # -- helpers -------------------------------------------------------
    def _collect(self) -> Settings:
        values: dict[str, object] = {}
        for key, label, low, high in self.FIELDS:
            raw = self.vars[key].get().strip()
            try:
                value = int(raw)
            except ValueError:
                raise ValueError(f"{label} must be a whole number.") from None
            if not low <= value <= high:
                raise ValueError(f"{label} must be between {low} and {high}.")
            values[key] = value
        values["auto_start_breaks"] = self.auto_breaks.get()
        values["auto_start_focus"] = self.auto_focus.get()
        return Settings(**values)  # type: ignore[arg-type]

    def _save(self) -> None:
        try:
            settings = self._collect()
        except ValueError as exc:
            messagebox.showwarning("Check your settings", str(exc), parent=self)
            return
        self.app.save_settings(settings)

    def _defaults(self) -> None:
        self.load(Settings())
