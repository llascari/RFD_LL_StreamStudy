"""Dark, calm theme built entirely from ttk styles."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#0f1115"
SURFACE = "#171b22"
SURFACE_ALT = "#212834"
BORDER = "#2b3340"
TEXT = "#e8ebf1"
MUTED = "#8c96a8"
ACCENT = "#6c8cff"
ACCENT_HOVER = "#8aa4ff"
ON_ACCENT = "#0b0d12"
SUCCESS = "#3fb98a"
DANGER = "#ff6b6b"
FOCUS_COLOR = "#6c8cff"
SHORT_COLOR = "#3fb98a"
LONG_COLOR = "#c58af9"


def font_family(root: tk.Misc) -> str:
    try:
        return tkfont.nametofont("TkDefaultFont").actual("family")
    except tk.TclError:  # pragma: no cover - unusual Tk builds
        return "Helvetica"


def apply_theme(root: tk.Tk) -> None:
    family = font_family(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover - platform without clam
        pass

    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)

    style.configure(".", background=BG, foreground=TEXT, font=(family, 10))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure(
        "Heading.TLabel", background=BG, foreground=TEXT, font=(family, 17, "bold")
    )
    style.configure(
        "Subheading.TLabel", background=BG, foreground=TEXT, font=(family, 11, "bold")
    )
    style.configure(
        "Clock.TLabel", background=BG, foreground=TEXT, font=(family, 62, "bold")
    )
    style.configure(
        "PhaseFocus.TLabel",
        background=BG,
        foreground=FOCUS_COLOR,
        font=(family, 12, "bold"),
    )
    style.configure(
        "PhaseShort.TLabel",
        background=BG,
        foreground=SHORT_COLOR,
        font=(family, 12, "bold"),
    )
    style.configure(
        "PhaseLong.TLabel",
        background=BG,
        foreground=LONG_COLOR,
        font=(family, 12, "bold"),
    )

    style.configure(
        "TButton",
        background=SURFACE_ALT,
        foreground=TEXT,
        borderwidth=0,
        focusthickness=0,
        padding=(14, 7),
        font=(family, 10),
    )
    style.map(
        "TButton",
        background=[("pressed", BORDER), ("active", BORDER)],
        foreground=[("disabled", MUTED)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=ON_ACCENT,
        borderwidth=0,
        focusthickness=0,
        padding=(22, 11),
        font=(family, 11, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", "#5b79e6"), ("active", ACCENT_HOVER), ("disabled", SURFACE_ALT)],
        foreground=[("disabled", MUTED)],
    )

    style.configure(
        "TNotebook",
        background=BG,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
        lightcolor=BG,
        darkcolor=BG,
        bordercolor=BG,
        highlightthickness=0,
    )
    style.configure(
        "TNotebook.Tab",
        background=SURFACE,
        foreground=MUTED,
        borderwidth=0,
        padding=(18, 9),
        lightcolor=SURFACE,
        darkcolor=SURFACE,
        bordercolor=SURFACE,
        focuscolor=SURFACE,
        font=(family, 10),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE_ALT)],
        foreground=[("selected", TEXT)],
        lightcolor=[("selected", SURFACE_ALT)],
        darkcolor=[("selected", SURFACE_ALT)],
        bordercolor=[("selected", SURFACE_ALT)],
        focuscolor=[("selected", SURFACE_ALT)],
    )

    for name in ("TEntry", "TSpinbox"):
        style.configure(
            name,
            fieldbackground=SURFACE_ALT,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=SURFACE_ALT,
            darkcolor=SURFACE_ALT,
            arrowcolor=MUTED,
            padding=(6, 5),
        )
        style.map(
            name,
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", SURFACE_ALT)],
            darkcolor=[("focus", SURFACE_ALT)],
        )

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        padding=(6, 4),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_ALT)],
        foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", SURFACE_ALT)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT), ("readonly", BORDER)],
        lightcolor=[("readonly", SURFACE_ALT)],
        darkcolor=[("readonly", SURFACE_ALT)],
    )

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=28,
        borderwidth=0,
        bordercolor=SURFACE,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_ALT,
        foreground=MUTED,
        relief="flat",
        borderwidth=0,
        padding=(6, 6),
        font=(family, 10, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", ON_ACCENT)],
    )
    style.map("Treeview.Heading", background=[("active", SURFACE_ALT)])

    style.configure(
        "TCheckbutton",
        background=BG,
        foreground=TEXT,
        focusthickness=0,
        focuscolor=BG,
        indicatorbackground=SURFACE_ALT,
        indicatorforeground=TEXT,
        upperbordercolor=BORDER,
        lowerbordercolor=BORDER,
    )
    style.map(
        "TCheckbutton",
        background=[("active", BG)],
        foreground=[("active", TEXT)],
        indicatorbackground=[("selected", ACCENT), ("pressed", BORDER)],
        indicatorforeground=[("selected", ON_ACCENT)],
    )

    style.configure(
        "Timer.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=SURFACE_ALT,
        bordercolor=SURFACE_ALT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=8,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_ALT,
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        arrowcolor=MUTED,
        gripcount=0,
        arrowsize=12,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("pressed", BORDER), ("active", BORDER)],
    )
