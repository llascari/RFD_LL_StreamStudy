"""Site finder tab: search USGS surface-water gages by state or nearby."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..models import Site
from .widgets import clear_tree, treeview

STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY", "PR",
)


class SitesView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._sites: dict[str, Site] = {}
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Site finder", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Active USGS surface-water gages reporting discharge, by state or near the loaded site.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(controls, text="State", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.state_var = tk.StringVar(value=str(self.app.settings.get("state", "NY")))
        self.state_combo = ttk.Combobox(
            controls, textvariable=self.state_var, values=STATES, width=5, state="readonly"
        )
        self.state_combo.pack(side="left")
        ttk.Button(
            controls, text="Search state", style="Accent.TButton", command=self._search_state
        ).pack(side="left", padx=(8, 4))
        ttk.Button(
            controls, text="Near current site", command=self._search_nearby
        ).pack(side="left", padx=4)
        ttk.Label(controls, text="Name", style="Muted.TLabel").pack(
            side="left", padx=(16, 6)
        )
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(controls, textvariable=self.name_var, width=20)
        name_entry.pack(side="left")
        name_entry.bind("<Return>", lambda _event: self._search_name())
        ttk.Button(controls, text="Find by name", command=self._search_name).pack(
            side="left", padx=(6, 0)
        )
        self.status_var = tk.StringVar(value="Pick a state, or search near the loaded site.")
        ttk.Label(
            controls, textvariable=self.status_var, style="Muted.TLabel"
        ).pack(side="left", padx=12)

        tree_frame, self.tree = treeview(
            self,
            {
                "site": ("Site", 100, "w"),
                "name": ("Station name", 420, "w"),
                "state": ("State", 55, "center"),
                "huc": ("HUC", 130, "w"),
                "elevation": ("Elevation (ft)", 110, "e"),
            },
            height=16,
        )
        tree_frame.grid(row=3, column=0, sticky="nsew")
        self.tree.column("name", stretch=True)
        self.tree.column("elevation", stretch=False)
        self.tree.bind("<Double-1>", lambda _event: self._load_selected())

        footer = ttk.Frame(self)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            footer, text="Load selected site", style="Accent.TButton", command=self._load_selected
        ).pack(side="left")
        ttk.Label(
            footer,
            text="Double-click a row to load it. Results are limited to the first 400 matches.",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

    # -- searching -----------------------------------------------------
    def _search_state(self) -> None:
        state = self.state_var.get().strip().upper()
        if not state:
            return
        self.app.settings["state"] = state
        work = lambda: self.app.providers["usgs"].search_sites(state=state)  # noqa: E731
        self._run(work, f"gages in {state}")

    def _search_name(self) -> None:
        term = self.name_var.get().strip()
        if not term:
            self.status_var.set("Type part of a station name, e.g. Irondequoit.")
            return
        state = self.state_var.get().strip().upper() or None
        work = lambda: self.app.providers["usgs"].search_by_name(  # noqa: E731
            term, state=state, limit=300
        )
        self._run(work, f'named "{term}"')

    def _search_nearby(self) -> None:
        bundle = self.app.bundle
        if bundle is None:
            messagebox.showinfo(
                "Load a site first", "Search near a site after loading one.", parent=self
            )
            return
        site = bundle.site
        radius = 0.5  # degrees, roughly 50 km
        bbox = (
            site.longitude - radius,
            site.latitude - radius,
            site.longitude + radius,
            site.latitude + radius,
        )
        work = lambda: self.app.providers["usgs"].search_sites(bbox=bbox)  # noqa: E731
        self._run(work, "gages within ~50 km")

    def _run(self, work, label: str) -> None:
        self.status_var.set(f"Searching {label}\u2026")
        self.app.run_async(work, lambda result, error: self._finish(result, error, label))

    def _finish(self, sites, error, label: str) -> None:
        if error is not None:
            self.status_var.set(f"Search failed: {error}")
            return
        sites = sites or []
        clear_tree(self.tree)
        self._sites.clear()
        for site in sites:
            if site.number in self._sites:
                continue
            self._sites[site.number] = site
            elevation = (
                f"{site.altitude_ft:,.0f}" if site.altitude_ft is not None else "\u2014"
            )
            self.tree.insert(
                "",
                "end",
                iid=site.number,
                values=(
                    site.number,
                    site.name,
                    site.state or "\u2014",
                    site.huc or "\u2014",
                    elevation,
                ),
            )
        count = len(self._sites)
        self.status_var.set(f"{count} {label}" if count else f"No {label} found")

    # -- loading ---------------------------------------------------------
    def _load_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        site = self._sites.get(selection[0])
        if site is None:
            return
        self.app.load_site(site.number)
        self.app.show_overview()
