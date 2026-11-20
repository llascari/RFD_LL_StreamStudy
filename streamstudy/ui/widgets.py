"""Reusable Tk widgets: stat cards, section headers and table helpers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import BAD, BG, GOOD, MUTED, SURFACE, TEXT, WARN, font_family


class StatCard(ttk.Frame):
    """A small KPI tile: caption, big value, unit and a delta/trend line."""

    def __init__(self, master: tk.Misc, caption: str, *, accent: str | None = None) -> None:
        super().__init__(master, style="Card.TFrame", padding=(14, 10))
        self.value_var = tk.StringVar(value="\u2014")
        self.detail_var = tk.StringVar(value="")

        top = ttk.Frame(self, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=caption.upper(), style="MutedCard.TLabel").pack(side="left")
        if accent:
            tk.Label(top, text="\u25cf", bg=SURFACE, fg=accent, font=("TkDefaultFont", 8)).pack(
                side="right"
            )

        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill="x", pady=(2, 0))
        self.value_label = ttk.Label(
            row, textvariable=self.value_var, style="Value.TLabel"
        )
        self.value_label.pack(side="left")
        self.unit_label = ttk.Label(row, text="", style="MutedCard.TLabel")
        self.unit_label.pack(side="left", padx=(5, 0), pady=(6, 0))

        self.detail_label = ttk.Label(
            self, textvariable=self.detail_var, style="MutedCard.TLabel"
        )
        self.detail_label.pack(anchor="w", pady=(2, 0))

    def set(
        self,
        value: str,
        unit: str = "",
        detail: str = "",
        *,
        tone: str = "muted",
    ) -> None:
        self.value_var.set(value)
        self.unit_label.configure(text=unit)
        self.detail_var.set(detail)
        color = {"good": GOOD, "warn": WARN, "bad": BAD, "muted": MUTED}[tone]
        self.detail_label.configure(foreground=color)


class SourceRow(ttk.Frame):
    """A line in the 'data sources' list: dot, network, detail, status."""

    def __init__(self, master: tk.Misc, network: str) -> None:
        super().__init__(master, style="Card.TFrame")
        self.dot = tk.Label(self, text="\u25cf", bg=SURFACE, fg=MUTED, font=("TkDefaultFont", 8))
        self.dot.pack(side="left", padx=(0, 8))
        ttk.Label(self, text=network, style="Card.TLabel", width=12).pack(side="left")
        self.detail_var = tk.StringVar(value="")
        ttk.Label(
            self, textvariable=self.detail_var, style="MutedCard.TLabel", anchor="w"
        ).pack(side="left", fill="x", expand=True)
        self.state_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.state_var, style="MutedCard.TLabel").pack(side="right")

    def set(self, detail: str, state: str = "ok", status_text: str = "") -> None:
        colors = {"ok": GOOD, "partial": WARN, "error": BAD, "idle": MUTED}
        self.dot.configure(fg=colors.get(state, MUTED))
        self.detail_var.set(detail)
        self.state_var.set(status_text)


def section_label(parent: tk.Misc, text: str) -> ttk.Label:
    label = ttk.Label(parent, text=text, style="Subheading.TLabel")
    label.pack(anchor="w", pady=(0, 6))
    return label


def treeview(
    parent: tk.Misc,
    columns: dict[str, tuple[str, int, str]],
    *,
    height: int = 8,
) -> tuple[ttk.Frame, ttk.Treeview]:
    """Create a scrollable treeview. ``columns`` maps key -> (heading, width, anchor)."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=tuple(columns), show="headings", height=height)
    for key, (heading, width, anchor) in columns.items():
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor=anchor, stretch=(key == list(columns)[-1]))
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    return frame, tree


def dot(parent: tk.Misc, color: str, size: int = 8) -> tk.Label:
    return tk.Label(parent, text="\u25cf", bg=BG, fg=color, font=(font_family(parent), size))


def hline(parent: tk.Misc, color: str = "#1c2833") -> tk.Frame:
    line = tk.Frame(parent, bg=color, height=1)
    line.pack(fill="x", pady=6)
    return line


def clear_tree(tree: ttk.Treeview) -> None:
    tree.delete(*tree.get_children())


def set_row_tone(tree: ttk.Treeview) -> None:
    tree.tag_configure("muted", foreground=MUTED)
    tree.tag_configure("text", foreground=TEXT)
