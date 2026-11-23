"""Dark 'deep water' theme built from ttk styles."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#0b1016"
SURFACE = "#121a23"
SURFACE_ALT = "#1a2530"
BORDER = "#27343f"
GRID = "#1c2833"
TEXT = "#e6eef5"
MUTED = "#8296a6"
ACCENT = "#3fa9f5"
ACCENT_HOVER = "#6dc0ff"
ON_ACCENT = "#06121c"
GOOD = "#35c48f"
WARN = "#f2b544"
BAD = "#ff6b6b"

SERIES_COLORS = {
    "discharge": "#4e9df0",
    "gage": "#f0a33a",
    "temperature": "#e0715f",
    "usgs": "#cc79a7",
    "cocorahs": "#009e73",
    "openmeteo": "#56b4e9",
    "nws": "#d55e00",
}


def font_family(root: tk.Misc) -> str:
    try:
        return tkfont.nametofont("TkDefaultFont").actual("family")
    except tk.TclError:  # pragma: no cover
        return "Helvetica"


def apply_theme(root: tk.Tk) -> None:
    family = font_family(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover
        pass

    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)

    style.configure(".", background=BG, foreground=TEXT, font=(family, 10))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Header.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("MutedCard.TLabel", background=SURFACE, foreground=MUTED)

    style.configure(
        "Title.TLabel", background=BG, foreground=TEXT, font=(family, 19, "bold")
    )
    style.configure(
        "Heading.TLabel", background=BG, foreground=TEXT, font=(family, 15, "bold")
    )
    style.configure(
        "Subheading.TLabel", background=BG, foreground=TEXT, font=(family, 11, "bold")
    )
    style.configure(
        "Value.TLabel", background=SURFACE, foreground=TEXT, font=(family, 20, "bold")
    )
    style.configure(
        "Link.TLabel", background=BG, foreground=ACCENT, font=(family, 9)
    )
    style.configure(
        "HeaderMuted.TLabel", background=SURFACE, foreground=MUTED, font=(family, 9)
    )
    style.configure(
        "Header.TLabel", background=SURFACE, foreground=TEXT, font=(family, 9)
    )

    style.configure(
        "TButton",
        background=SURFACE_ALT,
        foreground=TEXT,
        borderwidth=0,
        focusthickness=0,
        padding=(12, 6),
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
        padding=(16, 7),
        font=(family, 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", "#2f8fd0"), ("active", ACCENT_HOVER), ("disabled", SURFACE_ALT)],
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
    )
    style.configure(
        "TNotebook.Tab",
        background=SURFACE,
        foreground=MUTED,
        borderwidth=0,
        padding=(10, 8),
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
        style.map(name, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", SURFACE_ALT)])

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
    )

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=27,
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
        font=(family, 9, "bold"),
    )
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", ON_ACCENT)])
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
        indicatorbackground=[("selected", ACCENT), ("pressed", BORDER)],
        indicatorforeground=[("selected", ON_ACCENT)],
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
    style.map("Vertical.TScrollbar", background=[("pressed", BORDER), ("active", BORDER)])

    style.configure(
        "Status.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=SURFACE_ALT,
        bordercolor=SURFACE_ALT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=4,
    )
