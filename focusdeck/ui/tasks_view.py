"""The tasks tab: a lightweight task list stored in SQLite."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .theme import MUTED


class TasksView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(26, 20))
        self.app = app
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="Tasks", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Pick a task in the Timer tab to attach it to your focus sessions.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        entry_row = ttk.Frame(self)
        entry_row.grid(row=2, column=0, sticky="new")
        entry_row.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(entry_row)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._add())
        ttk.Button(
            entry_row, text="Add task", style="Accent.TButton", command=self._add
        ).grid(row=0, column=1, sticky="e")

        list_row = ttk.Frame(self)
        list_row.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
        self.rowconfigure(3, weight=1)
        list_row.columnconfigure(0, weight=1)
        list_row.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_row, columns=("status", "title"), show="headings", selectmode="browse"
        )
        self.tree.heading("status", text="")
        self.tree.heading("title", text="Task")
        self.tree.column("status", width=44, anchor="center", stretch=False)
        self.tree.column("title", width=420, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.tag_configure("done", foreground=MUTED)
        self.tree.bind("<Double-1>", lambda _e: self._toggle_selected())

        scroll = ttk.Scrollbar(list_row, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Button(
            buttons, text="Mark done / undone", command=self._toggle_selected
        ).pack(side="left")
        ttk.Button(buttons, text="Delete", command=self._delete_selected).pack(
            side="left", padx=8
        )
        ttk.Button(
            buttons, text="Focus on this task", command=self._focus_selected
        ).pack(side="left")

    # -- external API --------------------------------------------------
    def set_tasks(self, tasks: list) -> None:
        selected = self._selected_id()
        self.tree.delete(*self.tree.get_children())
        for task in tasks:
            self.tree.insert(
                "",
                "end",
                iid=str(task.id),
                values=("\u2713" if task.done else "\u25cb", task.title),
                tags=("done",) if task.done else (),
            )
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))

    def clear_input(self) -> None:
        self.entry.delete(0, "end")

    def focus_input(self) -> None:
        self.entry.focus_set()

    # -- helpers -------------------------------------------------------
    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _add(self) -> None:
        try:
            task = self.app.add_task(self.entry.get())
        except ValueError:
            messagebox.showwarning(
                "Empty task", "Type a task name before adding it.", parent=self
            )
            return
        self.clear_input()
        if self.tree.exists(str(task.id)):
            self.tree.selection_set(str(task.id))

    def _toggle_selected(self) -> None:
        task_id = self._selected_id()
        if task_id is None:
            return
        task = next((t for t in self.app.store.tasks() if t.id == task_id), None)
        if task is None:
            return
        self.app.set_task_done(task_id, not task.done)

    def _delete_selected(self) -> None:
        task_id = self._selected_id()
        if task_id is None:
            return
        self.app.delete_task(task_id)

    def _focus_selected(self) -> None:
        task_id = self._selected_id()
        if task_id is None:
            return
        self.app.set_active_task(task_id)
        self.app.show_timer()
