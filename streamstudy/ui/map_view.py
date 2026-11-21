"""Regional map with clickable USGS gages and flow/rain cross-correlation."""

from __future__ import annotations

import base64
import math
import tkinter as tk
from tkinter import ttk

from ..correlation import LagCorrelation, RegionalAnalysis
from ..models import Site
from .theme import (
    ACCENT,
    BAD,
    BG,
    BORDER,
    MUTED,
    ON_ACCENT,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    font_family,
)
from .widgets import clear_tree, treeview

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = "\u00a9 OpenStreetMap contributors"

ZOOM_BY_RADIUS = {0.25: 11, 0.5: 10, 1.0: 9, 2.0: 8}
RADII = (0.25, 0.5, 1.0, 2.0)


# --------------------------------------------------------------------------- #
# web-mercator helpers
# --------------------------------------------------------------------------- #
def zoom_for_radius(radius: float) -> int:
    nearest = min(ZOOM_BY_RADIUS, key=lambda value: abs(value - radius))
    return ZOOM_BY_RADIUS[nearest]


def global_pixel(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    size = 256.0 * (2**zoom)
    x = (longitude + 180.0) / 360.0 * size
    lat = math.radians(max(-85.05112878, min(85.05112878, latitude)))
    y = (
        1.0 - math.log(math.tan(lat) + 1.0 / math.cos(lat)) / math.pi
    ) / 2.0 * size
    return x, y


def pixel_to_latlon(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Inverse Web-Mercator for the global pixel grid at ``zoom``."""
    size = 256.0 * (2**zoom)
    longitude = x / size * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / size
    latitude = math.degrees(math.atan(math.sinh(n)))
    return latitude, longitude


def view_bbox(
    center: tuple[float, float], zoom: int, width: int, height: int
) -> tuple[float, float, float, float]:
    """(west, south, east, north) covered by a canvas of the given size."""
    centre_x, centre_y = global_pixel(*center, zoom)
    north, west = pixel_to_latlon(centre_x - width / 2, centre_y - height / 2, zoom)
    south, east = pixel_to_latlon(centre_x + width / 2, centre_y + height / 2, zoom)
    return west, south, east, north


def tiles_for_bbox(
    west: float, south: float, east: float, north: float, zoom: int
) -> list[tuple[int, int, int]]:
    x0, y0 = global_pixel(north, west, zoom)
    x1, y1 = global_pixel(south, east, zoom)
    count = 2**zoom
    coords: list[tuple[int, int, int]] = []
    for tile_x in range(int(x0 // 256), int(x1 // 256) + 1):
        for tile_y in range(int(y0 // 256), int(y1 // 256) + 1):
            if 0 <= tile_y < count:
                coords.append((zoom, tile_x % count, tile_y))
    return coords[:36]


def fetch_tiles(client, coords: list[tuple[int, int, int]]) -> dict[tuple[int, int, int], bytes]:
    """Download map tiles, skipping any that fail (the canvas degrades gracefully)."""
    tiles: dict[tuple[int, int, int], bytes] = {}
    for zoom, tile_x, tile_y in coords:
        try:
            tiles[(zoom, tile_x, tile_y)] = client.get_bytes(
                TILE_URL.format(z=zoom, x=tile_x, y=tile_y)
            )
        except Exception:  # noqa: BLE001 - optional basemap
            continue
    return tiles


def _blend(first: str, second: str, fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    a = tuple(int(first[index : index + 2], 16) for index in (1, 3, 5))
    b = tuple(int(second[index : index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(round(x + (y - x) * fraction) for x, y in zip(a, b))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def heat_colour(value: float) -> str:
    if value >= 0:
        return _blend(SURFACE_ALT, ACCENT, value)
    return _blend(SURFACE_ALT, BAD, -value)


# --------------------------------------------------------------------------- #
# map canvas
# --------------------------------------------------------------------------- #
class MapCanvas(tk.Canvas):
    def __init__(
        self, master: tk.Misc, on_select, on_view_change=None, on_resize=None
    ) -> None:
        super().__init__(master, bg=BG, highlightthickness=0, bd=0)
        self._on_select = on_select
        self._on_view_change = on_view_change
        self._on_resize = on_resize
        self._last_size = (0, 0)
        self._resize_job: str | None = None
        self._sites: list[Site] = []
        self._photos: dict[tuple[int, int, int], tk.PhotoImage] = {}
        self._center = (43.0, -77.0)
        self._current: str | None = None
        self._zoom = 10
        self._hover: Site | None = None
        self._filter = ""
        self._dx = 0.0
        self._dy = 0.0
        self._drag_origin: tuple[int, int] | None = None
        self._dragged = False

        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _event: self._set_hover(None))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda event: self._on_wheel(event, 1))
        self.bind("<Button-5>", lambda event: self._on_wheel(event, -1))

    # -- data ----------------------------------------------------------
    def set_map(
        self,
        center: tuple[float, float],
        zoom: int,
        sites: list[Site],
        tile_bytes: dict[tuple[int, int, int], bytes],
        current_id: str | None,
    ) -> None:
        self._center = center
        self._sites = list(sites)
        self._current = current_id
        self._zoom = max(4, min(15, int(zoom)))
        self._dx = 0.0
        self._dy = 0.0
        self._photos = {}
        for key, payload in tile_bytes.items():
            try:
                self._photos[key] = tk.PhotoImage(
                    data=base64.b64encode(payload).decode("ascii")
                )
            except tk.TclError:  # pragma: no cover - no PNG support in Tk
                continue
        self.redraw()

    # -- projection ----------------------------------------------------
    def _site_pixel(self, site: Site) -> tuple[float, float]:
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        centre_x, centre_y = global_pixel(*self._center, self._zoom)
        x, y = global_pixel(site.latitude, site.longitude, self._zoom)
        return (
            width / 2 + x - centre_x + self._dx,
            height / 2 + y - centre_y + self._dy,
        )

    def set_filter(self, text: str) -> None:
        """Filter visible markers by station name or number (case-insensitive)."""
        cleaned = text.strip().lower()
        if cleaned == self._filter:
            return
        self._filter = cleaned
        self._hover = None
        self.redraw()

    def visible_sites(self) -> list[Site]:
        if not self._filter:
            return list(self._sites)
        return [
            site
            for site in self._sites
            if self._filter in site.name.lower() or self._filter in site.number.lower()
        ]

    def _nearest(self, event_x: int, event_y: int, limit: float = 16.0) -> Site | None:
        best = None
        best_distance = limit**2
        for site in self.visible_sites():
            x, y = self._site_pixel(site)
            distance = (x - event_x) ** 2 + (y - event_y) ** 2
            if distance < best_distance:
                best_distance = distance
                best = site
        return best

    # -- events --------------------------------------------------------
    def _on_configure(self, event: tk.Event) -> None:
        size = (event.width, event.height)
        resized = self._last_size != (0, 0) and (
            abs(size[0] - self._last_size[0]) > 16
            or abs(size[1] - self._last_size[1]) > 16
        )
        self._last_size = size
        self.redraw()
        if resized and self._on_resize is not None and not self._dragged:
            if self._resize_job is not None:
                try:
                    self.after_cancel(self._resize_job)
                except tk.TclError:
                    pass
            self._resize_job = self.after(350, self._notify_resize)

    def _notify_resize(self) -> None:
        self._resize_job = None
        if self._on_resize is not None:
            self._on_resize(self._center[0], self._center[1], self._zoom)

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._nearest(event.x, event.y))

    def _set_hover(self, site: Site | None) -> None:
        if site == self._hover:
            return
        self._hover = site
        self.redraw()

    def _on_press(self, event: tk.Event) -> None:
        self._drag_origin = (event.x, event.y)
        self._dragged = False
        self.configure(cursor="fleur")

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        dx = event.x - self._drag_origin[0]
        dy = event.y - self._drag_origin[1]
        if abs(dx) + abs(dy) > 4:
            self._dragged = True
        self._dx, self._dy = float(dx), float(dy)
        self._hover = None
        self.redraw()

    def _on_release(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        self.configure(cursor="")
        if self._dragged:
            centre_x, centre_y = global_pixel(*self._center, self._zoom)
            latitude, longitude = pixel_to_latlon(
                centre_x - self._dx, centre_y - self._dy, self._zoom
            )
            self._dx = self._dy = 0.0
            self._dragged = False
            self._drag_origin = None
            if self._on_view_change is not None:
                self._on_view_change(latitude, longitude, self._zoom)
            self.redraw()
            return
        self._drag_origin = None
        site = self._nearest(event.x, event.y)
        if site is not None:
            self._on_select(site)

    def _on_wheel(self, event: tk.Event, direction: int | None = None) -> str:
        if direction is None:
            direction = 1 if getattr(event, "delta", 0) > 0 else -1
        new_zoom = max(4, min(15, self._zoom + direction))
        if new_zoom == self._zoom:
            return "break"
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        centre_x, centre_y = global_pixel(*self._center, self._zoom)
        offset_x = getattr(event, "x", width / 2) - width / 2
        offset_y = getattr(event, "y", height / 2) - height / 2
        factor = 2 ** (new_zoom - self._zoom)
        global_x = (centre_x + offset_x) * factor
        global_y = (centre_y + offset_y) * factor
        latitude, longitude = pixel_to_latlon(
            global_x - offset_x, global_y - offset_y, new_zoom
        )
        if self._on_view_change is not None:
            self._on_view_change(latitude, longitude, new_zoom)
        return "break"

    # -- drawing -------------------------------------------------------
    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        family = font_family(self)
        if width < 80 or height < 80:
            return

        centre_x, centre_y = global_pixel(*self._center, self._zoom)
        drawn_tiles = 0
        for (zoom, tile_x, tile_y), photo in self._photos.items():
            x = width / 2 + tile_x * 256 - centre_x + self._dx
            y = height / 2 + tile_y * 256 - centre_y + self._dy
            if x > width or y > height or x + 256 < 0 or y + 256 < 0:
                continue
            self.create_image(x, y, image=photo, anchor="nw")
            drawn_tiles += 1

        if drawn_tiles == 0:
            for step in range(1, 5):
                x = width * step / 5
                y = height * step / 5
                self.create_line(x, 0, x, height, fill=SURFACE_ALT)
                self.create_line(0, y, width, y, fill=SURFACE_ALT)
            self.create_text(
                width / 2,
                height - 26,
                text="Basemap tiles unavailable \u2014 schematic gage positions",
                fill=MUTED,
                font=(family, 9),
            )

        shown = 0
        for site in self.visible_sites():
            x, y = self._site_pixel(site)
            if not (-20 <= x <= width + 20 and -20 <= y <= height + 20):
                continue
            shown += 1
            current = site.number == self._current
            radius = 7 if current else 4
            self.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=ACCENT if current else "#4e9df0",
                outline="#ffffff" if current else BG,
                width=2 if current else 1,
            )
            if current:
                self.create_oval(
                    x - 11, y - 11, x + 11, y + 11, outline=ACCENT, width=1
                )
                self.create_text(
                    x + 14,
                    y,
                    text="this gage",
                    anchor="w",
                    fill=TEXT,
                    font=(family, 8, "bold"),
                )

        if self._filter:
            legend = (
                f"{len(self.visible_sites())} of {len(self._sites)} gages match "
                f"\u00b7 click a dot to load it"
            )
        else:
            legend = f"{shown} of {len(self._sites)} gages shown \u00b7 click a dot to load it"
        self.create_text(
            10,
            10,
            text=legend,
            anchor="nw",
            fill=MUTED,
            font=(family, 8),
        )
        self.create_text(
            10,
            height - 6,
            text="drag to pan \u00b7 scroll to zoom",
            anchor="sw",
            fill=MUTED,
            font=(family, 7),
        )
        self.create_text(
            width - 8,
            height - 5,
            text=ATTRIBUTION,
            anchor="se",
            fill=MUTED,
            font=(family, 7),
        )

        if self._hover is not None:
            site = self._hover
            lines = [f"USGS {site.number}", site.name]
            detail = [site.state or "", site.site_type or ""]
            if site.drainage_area_sq_mi:
                detail.append(f"{site.drainage_area_sq_mi:,.0f} mi\u00b2")
            if any(detail):
                lines.append("  \u00b7  ".join(part for part in detail if part))
            text = "\n".join(lines)
            box_w = max(len(line) for line in lines) * 6.0 + 16
            box_h = 13 * len(lines) + 8
            self.create_rectangle(
                8, 28, 8 + box_w, 28 + box_h, fill=SURFACE_ALT, outline=BORDER
            )
            self.create_text(
                16,
                34,
                text=text,
                anchor="nw",
                fill=TEXT,
                font=(family, 8),
            )


# --------------------------------------------------------------------------- #
# correlation heatmap
# --------------------------------------------------------------------------- #
class HeatmapCanvas(tk.Canvas):
    def __init__(self, master: tk.Misc, height: int = 250) -> None:
        super().__init__(master, height=height, bg=BG, highlightthickness=0, bd=0)
        self._ids: list[str] = []
        self._labels: dict[str, str] = {}
        self._pairs: dict[tuple[str, str], LagCorrelation] = {}
        self._empty = "No correlation yet"
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_data(
        self,
        ids: list[str],
        labels: dict[str, str],
        pairs: dict[tuple[str, str], LagCorrelation],
        *,
        empty_text: str | None = None,
    ) -> None:
        self._ids = list(ids)
        self._labels = dict(labels)
        self._pairs = dict(pairs)
        if empty_text is not None:
            self._empty = empty_text
        self.redraw()

    def _cell(self, first: str, second: str) -> tuple[float, int] | None:
        if first == second:
            return 1.0, 0
        pair = self._pairs.get((first, second))
        if pair is not None:
            return pair.r, pair.lag_days
        pair = self._pairs.get((second, first))
        if pair is not None:
            return pair.r, -pair.lag_days
        return None

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        family = font_family(self)
        if width < 80 or height < 60:
            return
        if len(self._ids) < 2:
            self.create_text(
                width / 2,
                height / 2,
                text=self._empty,
                fill=MUTED,
                font=(family, 9),
            )
            return

        count = len(self._ids)
        left, top = 74, 26
        cell = min((width - left - 8) / count, (height - top - 8) / count, 46)

        for index, site_id in enumerate(self._ids):
            label = self._labels.get(site_id, site_id)
            self.create_text(
                left + cell * (index + 0.5),
                top - 12,
                text=site_id[-4:],
                fill=MUTED,
                font=(family, 7),
            )
            self.create_text(
                left - 6,
                top + cell * (index + 0.5),
                text=label,
                anchor="e",
                fill=MUTED,
                font=(family, 7),
            )

        for row, first in enumerate(self._ids):
            for column, second in enumerate(self._ids):
                value = self._cell(first, second)
                x = left + column * cell
                y = top + row * cell
                if value is None:
                    self.create_rectangle(
                        x + 1, y + 1, x + cell - 1, y + cell - 1,
                        fill=SURFACE, outline=BORDER,
                    )
                    continue
                r, lag = value
                self.create_rectangle(
                    x + 1,
                    y + 1,
                    x + cell - 1,
                    y + cell - 1,
                    fill=heat_colour(r),
                    outline=SURFACE,
                )
                text_fill = ON_ACCENT if abs(r) > 0.55 else TEXT
                self.create_text(
                    x + cell / 2,
                    y + cell / 2 - 4,
                    text=f"{r:.2f}",
                    fill=text_fill,
                    font=(family, 8, "bold"),
                )
                if lag:
                    self.create_text(
                        x + cell / 2,
                        y + cell / 2 + 9,
                        text=f"{lag:+d} d",
                        fill=text_fill,
                        font=(family, 7),
                    )


# --------------------------------------------------------------------------- #
# view
# --------------------------------------------------------------------------- #
class MapView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._sites: list[Site] = []
        self._analysis: RegionalAnalysis | None = None
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Map & Correlation", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Loading nearby gages\u2026",
            style="Muted.TLabel",
            wraplength=560,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(controls, text="Filter", style="Muted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(controls, textvariable=self.filter_var, width=18)
        filter_entry.pack(side="left", padx=(0, 12))
        filter_entry.bind(
            "<KeyRelease>", lambda _event: self.map.set_filter(self.filter_var.get())
        )
        ttk.Label(controls, text="Radius", style="Muted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.radius_var = tk.StringVar(value=self._radius_label())
        radius_box = ttk.Combobox(
            controls,
            textvariable=self.radius_var,
            width=10,
            state="readonly",
            values=[self._label_for(radius) for radius in RADII],
        )
        radius_box.pack(side="left")
        radius_box.bind("<<ComboboxSelected>>", self._on_radius)
        ttk.Button(controls, text="Recenter", command=self._recenter).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(controls, text="Reload map", command=self._reload_map).pack(
            side="left", padx=(4, 0)
        )

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=3, uniform="map")
        body.columnconfigure(1, weight=2, uniform="map")
        body.rowconfigure(0, weight=1)

        map_frame = ttk.Frame(body)
        map_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        map_frame.columnconfigure(0, weight=1)
        map_frame.rowconfigure(0, weight=1)
        self.map = MapCanvas(
            map_frame,
            on_select=self._on_site_clicked,
            on_view_change=self._on_view_change,
            on_resize=self._on_resize,
        )
        self.map.grid(row=0, column=0, sticky="nsew")

        panel = ttk.Frame(body)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)

        ttk.Label(panel, text="Regional cross-correlation", style="Subheading.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        corr_controls = ttk.Frame(panel)
        corr_controls.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        ttk.Label(corr_controls, text="History", style="Muted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.years_var = tk.StringVar(value=f"{self.app.map_years} years")
        years_box = ttk.Combobox(
            corr_controls,
            textvariable=self.years_var,
            width=8,
            state="readonly",
            values=["1 year", "2 years", "3 years"],
        )
        years_box.pack(side="left")
        years_box.bind("<<ComboboxSelected>>", self._on_years)
        ttk.Button(corr_controls, text="Recompute", command=self._recompute).pack(
            side="left", padx=(8, 0)
        )
        self.corr_status = ttk.Label(corr_controls, text="", style="Muted.TLabel")
        self.corr_status.pack(side="right")

        self.heatmap = HeatmapCanvas(panel, height=190)
        self.heatmap.grid(row=2, column=0, sticky="ew")

        self.pairs_var = tk.StringVar(value="")
        ttk.Label(
            panel,
            textvariable=self.pairs_var,
            style="Muted.TLabel",
            wraplength=440,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(6, 8))

        rain_frame, self.rain_tree = treeview(
            panel,
            {
                "gage": ("Gage", 85, "w"),
                "source": ("Rain source", 150, "w"),
                "r": ("r", 48, "e"),
                "lag": ("Lag", 48, "e"),
                "n": ("n", 44, "e"),
            },
            height=5,
        )
        rain_frame.grid(row=4, column=0, sticky="nsew")

        ttk.Label(
            panel,
            text="Log-flow Pearson r at the best lag (\u00b15 d). A positive lag means the second gage "
            "follows the first; in rain rows, the flow follows the rain. Heatmap columns show the "
            "last four digits of the site number.",
            style="Muted.TLabel",
            wraplength=440,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))

    # -- helpers -------------------------------------------------------
    def _label_for(self, radius: float) -> str:
        return f"{radius:g}\u00b0"

    def _radius_label(self) -> str:
        return self._label_for(float(self.app.map_radius))

    def _on_radius(self, _event: tk.Event | None = None) -> None:
        try:
            radius = float(self.radius_var.get().rstrip("\u00b0"))
        except ValueError:
            return
        self.app.set_map_radius(radius)

    def _on_years(self, _event: tk.Event | None = None) -> None:
        try:
            years = int(self.years_var.get().split()[0])
        except (ValueError, IndexError):
            return
        self.app.set_map_years(years)

    def _reload_map(self) -> None:
        self.app.request_map(force=True)

    def _recenter(self) -> None:
        self.app.recenter_map()

    def _on_view_change(self, latitude: float, longitude: float, zoom: int) -> None:
        self.app.request_map_view(latitude, longitude, zoom)

    def _on_resize(self, latitude: float, longitude: float, zoom: int) -> None:
        """Window resized: fetch tiles/gages for the newly exposed area."""
        self.app.request_map_view(latitude, longitude, zoom, force=True)

    def map_size(self) -> tuple[int, int]:
        """Canvas size, with a sane fallback while the tab is still hidden."""
        width = self.map.winfo_width()
        height = self.map.winfo_height()
        return (width if width > 50 else 900, height if height > 50 else 700)

    def _recompute(self) -> None:
        self.app.request_regional(force=True)

    def _on_site_clicked(self, site: Site) -> None:
        self.app.load_site(site.number)

    # -- app callbacks -------------------------------------------------
    def set_site(self, site: Site) -> None:
        self.caption.configure(text=f"Gages around USGS {site.number} \u2014 {site.name}")

    def show_map_loading(self) -> None:
        self.caption.configure(text="Loading nearby gages and basemap tiles\u2026")
        self.corr_status.configure(text="")

    def set_map(
        self,
        center: tuple[float, float],
        zoom: int,
        sites: list[Site],
        tiles: dict[tuple[int, int, int], bytes],
        current_id: str,
    ) -> None:
        self._sites = list(sites)
        self.map.set_map(center, zoom, sites, tiles, current_id)
        self.map.set_filter(self.filter_var.get())
        self.caption.configure(
            text=f"USGS {current_id}  \u00b7  {len(sites)} gages in view  \u00b7  zoom {zoom}"
        )

    def show_correlation_loading(self) -> None:
        self.corr_status.configure(text="analysing\u2026")

    def set_correlation(self, analysis: RegionalAnalysis) -> None:
        self._analysis = analysis
        ids = [
            site.number
            for site in analysis.sites
            if site.number in analysis.flow
        ]
        labels = {site_id: analysis.short_label(site_id) for site_id in ids}
        self.heatmap.set_data(
            ids,
            labels,
            analysis.flow_pairs,
            empty_text="Not enough overlapping daily flows to correlate",
        )

        pairs = analysis.strongest_pairs(3)
        if pairs:
            lines = []
            for first, second, correlation in pairs:
                lines.append(
                    f"{analysis.short_label(first)} \u2194 {analysis.short_label(second)}: "
                    f"r {correlation.r:+.2f} at {correlation.lag_days:+d} d"
                )
            self.pairs_var.set("Strongest pairs \u2014 " + "   \u00b7   ".join(lines))
        else:
            self.pairs_var.set("Not enough overlapping daily flows to correlate.")

        clear_tree(self.rain_tree)
        rows = sorted(
            analysis.rain_pairs.items(), key=lambda item: abs(item[1].r), reverse=True
        )
        for (site_id, source), correlation in rows[:12]:
            self.rain_tree.insert(
                "",
                "end",
                values=(
                    analysis.short_label(site_id),
                    source,
                    f"{correlation.r:+.2f}",
                    f"{correlation.lag_days:+d} d",
                    correlation.n,
                ),
            )
        if not rows:
            self.rain_tree.insert(
                "", "end", values=("\u2014", "no paired rain/flow record", "", "", "")
            )

        self.corr_status.configure(text=f"{len(ids)} gages")
        if analysis.errors:
            self.caption.configure(
                text=f"{len(analysis.errors)} correlation warning(s) \u2014 see README"
            )
