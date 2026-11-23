"""Canvas-based time-series charts (lines and grouped bars) with hover readout.

Deliberately dependency-free: the app ships with no third-party packages, so
everything is drawn with Tk canvas primitives.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..analysis import nice_step
from .theme import (
    ACCENT,
    BORDER,
    GRID,
    MUTED,
    SERIES_COLORS,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    font_family,
)


@dataclass
class ChartSeries:
    name: str
    points: list[tuple[datetime, float]] = field(default_factory=list)
    color: str = "#4e9df0"
    kind: str = "line"  # "line" | "bar"
    width: int = 2
    dashed: bool = False


class ChartCanvas(tk.Canvas):
    """A small chart widget: one shared value axis, time on the x axis."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 220,
        title: str = "",
        unit: str = "",
        empty_text: str = "No data yet",
    ) -> None:
        super().__init__(
            master, height=height, bg=SURFACE, highlightthickness=0, bd=0, takefocus=0
        )
        self._all_series: list[ChartSeries] = []
        self._title = title
        self._unit = unit
        self._empty_text = empty_text
        self._hover_x: int | None = None
        self._hover_data: tuple[datetime, list[tuple[str, float]]] | None = None
        self._log = False

        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    # -- public API ----------------------------------------------------
    def set_series(
        self,
        series: list[ChartSeries],
        *,
        title: str | None = None,
        unit: str | None = None,
        empty_text: str | None = None,
    ) -> None:
        self._all_series = [s for s in series if s.points]
        if title is not None:
            self._title = title
        if unit is not None:
            self._unit = unit
        if empty_text is not None:
            self._empty_text = empty_text
        self._hover_x = None
        self._hover_data = None
        self.redraw()

    def set_log(self, enabled: bool) -> None:
        self._log = bool(enabled)
        self.redraw()

    # -- events --------------------------------------------------------
    def _on_motion(self, event: tk.Event) -> None:
        if self._hover_x is not None and abs(event.x - self._hover_x) < 4:
            return
        self._hover_x = event.x
        self.redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover_x = None
        self._hover_data = None
        self.redraw()

    # -- drawing -------------------------------------------------------
    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        family = font_family(self)
        if width < 90 or height < 80:
            return

        series = [s for s in self._all_series if s.points]
        if not series:
            self.create_text(
                width / 2,
                height / 2,
                text=self._empty_text,
                fill=MUTED,
                font=(family, 10),
            )
            return

        left, right, top, bottom = 54, 16, 44, 24
        plot_w = max(10, width - left - right)
        plot_h = max(10, height - top - bottom)

        times = [point[0] for s in series for point in s.points]
        values = [point[1] for s in series for point in s.points]
        start, end = min(times), max(times)
        if end <= start:
            end = start + timedelta(hours=6)
        span_seconds = (end - start).total_seconds()

        has_bars = any(s.kind == "bar" for s in series)
        use_log = self._log and not has_bars and min(values) > 0
        transform = math.log10 if use_log else (lambda value: value)

        low, high = min(values), max(values)
        if has_bars:
            low = min(0.0, low)
        low_t, high_t = transform(low), transform(high)
        if high_t == low_t:
            high_t = low_t + (abs(low_t) * 0.1 or 1.0)
        pad = (high_t - low_t) * 0.08
        low_t -= pad
        high_t += pad
        if has_bars and low >= 0:
            low_t = transform(0.0)

        step = nice_step(high_t - low_t, 4)
        tick = math.floor(low_t / step) * step
        ticks = []
        while tick <= high_t + step * 0.001:
            ticks.append(tick)
            tick += step

        def x_of(moment: datetime) -> float:
            return left + (moment - start).total_seconds() / span_seconds * plot_w

        def y_of(value: float) -> float:
            return top + (high_t - transform(value)) / (high_t - low_t) * plot_h

        # -- grid & value labels
        for value in ticks:
            y = top + (high_t - value) / (high_t - low_t) * plot_h
            if y < top - 1 or y > top + plot_h + 1:
                continue
            self.create_line(left, y, left + plot_w, y, fill=GRID)
            label = 10 ** value if use_log else value
            self.create_text(
                left - 8,
                y,
                text=_format_tick(label, step),
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )

        # -- time labels
        label_count = 5 if plot_w > 480 else 4
        for index in range(label_count):
            fraction = index / (label_count - 1)
            moment = start + timedelta(seconds=span_seconds * fraction)
            x = left + plot_w * fraction
            self.create_line(x, top, x, top + plot_h, fill=GRID, dash=(1, 4))
            fmt = "%b %d" if span_seconds > 3 * 86400 else "%b %d\n%H:%M"
            anchor = "w" if index == 0 else ("e" if index == label_count - 1 else "center")
            self.create_text(
                x,
                top + plot_h + 11,
                text=moment.astimezone().strftime(fmt),
                fill=MUTED,
                font=(family, 8),
                justify="center",
                anchor=anchor,
            )

        self.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill=BORDER)

        # -- bars (grouped by shared timestamp)
        bars = [s for s in series if s.kind == "bar"]
        if bars:
            unique_times = sorted({point[0] for s in bars for point in s.points})
            slot = plot_w / max(1, len(unique_times))
            bar_width = max(3.0, min(20.0, slot * 0.75 / len(bars)))
            zero_y = y_of(max(0.0, low))
            for bar_index, bar in enumerate(bars):
                offset = (bar_index - (len(bars) - 1) / 2) * bar_width
                for moment, value in bar.points:
                    if value <= 0:
                        continue
                    x = x_of(moment) + offset
                    y = y_of(value)
                    self.create_rectangle(
                        x - bar_width / 2 + 0.5,
                        y,
                        x + bar_width / 2 - 0.5,
                        zero_y,
                        fill=bar.color,
                        outline="",
                    )

        # -- lines
        for line in (s for s in series if s.kind != "bar"):
            pixels = [(x_of(t), y_of(v)) for t, v in line.points]
            if len(pixels) > 1:
                flat = [coord for point in pixels for coord in point]
                options = {
                    "fill": line.color,
                    "width": line.width,
                    "capstyle": "round",
                    "joinstyle": "round",
                }
                if line.dashed:
                    options["dash"] = (5, 4)
                self.create_line(*flat, **options)
            last_x, last_y = pixels[-1]
            radius = 3
            self.create_oval(
                last_x - radius,
                last_y - radius,
                last_x + radius,
                last_y + radius,
                fill=line.color,
                outline=SURFACE,
            )

        # -- titles & legend
        if self._title:
            self.create_text(left, 12, text=self._title, anchor="w", fill=TEXT, font=(family, 10, "bold"))
        if self._unit:
            self.create_text(
                left + plot_w, 12, text=self._unit, anchor="e", fill=MUTED, font=(family, 9)
            )

        legend_x = left
        legend_font = tkfont.Font(family=family, size=8)
        for entry in (series if len(series) > 1 else []):
            symbol_w = 16
            if entry.kind == "bar":
                self.create_rectangle(
                    legend_x, 27, legend_x + 9, 36, fill=entry.color, outline=""
                )
            else:
                options = {
                    "fill": entry.color,
                    "width": entry.width,
                    "capstyle": "round",
                }
                if entry.dashed:
                    options["dash"] = (4, 3)
                self.create_line(legend_x, 31, legend_x + symbol_w, 31, **options)
            text_width = legend_font.measure(entry.name)
            self.create_text(
                legend_x + symbol_w + 4, 31, text=entry.name, anchor="w", fill=MUTED, font=(family, 8)
            )
            legend_x += symbol_w + text_width + 22

        # -- hover readout
        if self._hover_x is not None and left <= self._hover_x <= left + plot_w:
            fraction = (self._hover_x - left) / plot_w
            moment = start + timedelta(seconds=span_seconds * fraction)
            nearest = None
            for entry in series:
                candidate = min(entry.points, key=lambda point: abs((point[0] - moment).total_seconds()))
                if nearest is None or abs((candidate[0] - moment).total_seconds()) < abs(
                    (nearest[0] - moment).total_seconds()
                ):
                    nearest = candidate
            if nearest is not None:
                x = x_of(nearest[0])
                self.create_line(x, top, x, top + plot_h, fill=MUTED, dash=(2, 3))
                rows = []
                for entry in series:
                    _, value = min(
                        entry.points, key=lambda point: abs((point[0] - nearest[0]).total_seconds())
                    )
                    rows.append((entry.name, value))
                self._draw_tooltip(nearest[0], rows, x, top, width, family)

    def _draw_tooltip(self, moment, rows, x, top, width, family) -> None:
        lines = [moment.astimezone().strftime("%b %d, %H:%M")] + [
            f"{name}: {value:,.2f}" for name, value in rows
        ]
        font = (family, 8)
        box_w = max(len(line) for line in lines) * 5.6 + 16
        box_h = 14 * len(lines) + 8
        box_x = x + 12 if x + 12 + box_w < width - 8 else x - 12 - box_w
        box_x = max(8, box_x)
        box_y = top + 4
        self.create_rectangle(
            box_x,
            box_y,
            box_x + box_w,
            box_y + box_h,
            fill=SURFACE_ALT,
            outline=BORDER,
        )
        self.create_text(
            box_x + 8,
            box_y + 6,
            text="\n".join(lines),
            anchor="nw",
            fill=TEXT,
            font=font,
        )


def _format_tick(value: float, step: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if step >= 1:
        return f"{value:.0f}"
    if step >= 0.1:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _padded_range(values: list[float]) -> tuple[float, float]:
    low, high = min(values), max(values)
    if high - low < 1e-9:
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.08
    return low - pad, high + pad


def _tick_values(low: float, high: float, step: float) -> list[float]:
    start = math.floor(low / step) * step
    values: list[float] = []
    value = start
    while value <= high + step * 1e-6 and len(values) < 14:
        if value >= low - step * 1e-6:
            values.append(value)
        value += step
    return values


class SignedScatterChart(tk.Canvas):
    """Scatter plot with signed axes, an optional regression line and hover."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 260,
        title: str = "",
        x_unit: str = "",
        y_unit: str = "",
        empty_text: str = "No paired days yet",
    ) -> None:
        super().__init__(
            master, height=height, bg=SURFACE, highlightthickness=0, bd=0, takefocus=0
        )
        self._points: list[tuple[float, float]] = []
        self._fit: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._title = title
        self._x_unit = x_unit
        self._y_unit = y_unit
        self._empty = empty_text
        self._hover: tuple[float, float] | None = None
        self._geometry: tuple[float, float, float, float, float, float, float, float] | None = None

        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _event: self._set_hover(None))

    def set_data(
        self,
        points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
        *,
        fit: tuple[tuple[float, float], tuple[float, float]] | None = None,
        title: str | None = None,
        empty_text: str | None = None,
    ) -> None:
        self._points = list(points)
        self._fit = fit
        if title is not None:
            self._title = title
        if empty_text is not None:
            self._empty = empty_text
        self._hover = None
        self.redraw()

    def _pixel(self, x_value: float, y_value: float) -> tuple[float, float]:
        geom = self._geometry
        if geom is None:
            return 0.0, 0.0
        left, top, plot_w, plot_h, xmin, xmax, ymin, ymax = geom
        x = left + (x_value - xmin) / (xmax - xmin) * plot_w
        y = top + (ymax - y_value) / (ymax - ymin) * plot_h
        return x, y

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._nearest(event.x, event.y))

    def _nearest(self, x: float, y: float) -> tuple[float, float] | None:
        geom = self._geometry
        if geom is None:
            return None
        best = None
        best_distance = 18.0**2
        for point in self._points:
            px, py = self._pixel(*point)
            distance = (px - x) ** 2 + (py - y) ** 2
            if distance < best_distance:
                best = point
                best_distance = distance
        return best

    def _set_hover(self, point: tuple[float, float] | None) -> None:
        if point == self._hover:
            return
        self._hover = point
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        family = font_family(self)
        left, top, right, bottom = 54, 30, 14, 42
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)

        if len(self._points) < 2:
            self.create_text(
                width / 2, height / 2, text=self._empty, fill=MUTED, font=(family, 10)
            )
            if self._title:
                self.create_text(
                    left, 12, text=self._title, anchor="w", fill=TEXT, font=(family, 10, "bold")
                )
            return

        xs = [point[0] for point in self._points]
        ys = [point[1] for point in self._points]
        xmin, xmax = _padded_range(xs)
        ymin, ymax = _padded_range(ys)
        self._geometry = (left, top, plot_w, plot_h, xmin, xmax, ymin, ymax)

        xstep = nice_step(xmax - xmin, 5)
        ystep = nice_step(ymax - ymin, 5)
        for value in _tick_values(xmin, xmax, xstep):
            x, _y = self._pixel(value, ymin)
            self.create_line(x, top, x, top + plot_h, fill=GRID)
            self.create_text(
                x,
                top + plot_h + 10,
                text=_format_tick(value, xstep),
                fill=MUTED,
                font=(family, 8),
                anchor="n",
            )
        for value in _tick_values(ymin, ymax, ystep):
            _x, y = self._pixel(xmin, value)
            self.create_line(left, y, left + plot_w, y, fill=GRID)
            self.create_text(
                left - 8,
                y,
                text=_format_tick(value, ystep),
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )

        if xmin < 0 < xmax:
            x, _y = self._pixel(0.0, ymin)
            self.create_line(x, top, x, top + plot_h, fill=BORDER, width=1)
        if ymin < 0 < ymax:
            _x, y = self._pixel(xmin, 0.0)
            self.create_line(left, y, left + plot_w, y, fill=BORDER, width=1)
        self.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill=BORDER)
        self.create_line(left, top, left, top + plot_h, fill=BORDER)

        if self._fit is not None:
            self.create_line(
                *self._pixel(*self._fit[0]),
                *self._pixel(*self._fit[1]),
                fill=ACCENT,
                width=1.3,
                dash=(5, 4),
            )

        for point in self._points:
            x, y = self._pixel(*point)
            self.create_oval(x - 2.2, y - 2.2, x + 2.2, y + 2.2, fill=SERIES_COLORS["discharge"], outline="")

        if self._hover is not None:
            x, y = self._pixel(*self._hover)
            self.create_oval(
                x - 5, y - 5, x + 5, y + 5, outline=SERIES_COLORS["gage"], width=1.5
            )
            label = f"{self._hover[0]:.1f} {self._x_unit} -> {self._hover[1]:.1f} {self._y_unit}"
            box_w = len(label) * 5.4 + 12
            box_x = x + 10 if x + 10 + box_w < width - 6 else x - 10 - box_w
            box_x = max(6, box_x)
            self.create_rectangle(
                box_x, top + 2, box_x + box_w, top + 20, fill=SURFACE_ALT, outline=BORDER
            )
            self.create_text(
                box_x + 6,
                top + 11,
                text=label,
                anchor="w",
                fill=TEXT,
                font=(family, 8),
            )

        if self._title:
            self.create_text(
                left, 12, text=self._title, anchor="w", fill=TEXT, font=(family, 10, "bold")
            )
        if self._y_unit:
            self.create_text(
                left + plot_w, 12, text=self._y_unit, anchor="e", fill=MUTED, font=(family, 9)
            )
        if self._x_unit:
            self.create_text(
                left + plot_w,
                top + plot_h + 26,
                text=self._x_unit,
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )


class ScatterChart(tk.Canvas):
    """Scatter plot with an optional fitted line and one highlighted point."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 280,
        title: str = "",
        x_unit: str = "",
        y_unit: str = "",
        empty_text: str = "No events yet",
    ) -> None:
        super().__init__(
            master, height=height, bg=SURFACE, highlightthickness=0, bd=0, takefocus=0
        )
        self._points: list[tuple[float, float]] = []
        self._slope: float | None = None
        self._highlight: tuple[float, float] | None = None
        self._title = title
        self._x_unit = x_unit
        self._y_unit = y_unit
        self._empty = empty_text
        self._hover: tuple[float, float] | None = None
        self._geometry: tuple[float, float, float, float, float, float] | None = None

        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _event: self._set_hover(None))

    # -- API -----------------------------------------------------------
    def set_data(
        self,
        points: list[tuple[float, float]],
        *,
        slope: float | None = None,
        highlight: tuple[float, float] | None = None,
        title: str | None = None,
        empty_text: str | None = None,
    ) -> None:
        self._points = list(points)
        self._slope = slope
        self._highlight = highlight
        if title is not None:
            self._title = title
        if empty_text is not None:
            self._empty = empty_text
        self._hover = None
        self.redraw()

    # -- events --------------------------------------------------------
    def _pixel(self, x_value: float, y_value: float) -> tuple[float, float]:
        left, top, plot_w, plot_h, xmax, ymax = self._geometry or (0, 0, 1, 1, 1, 1)
        return (
            left + x_value / xmax * plot_w,
            top + (ymax - y_value) / ymax * plot_h,
        )

    def _on_motion(self, event: tk.Event) -> None:
        if not self._points or self._geometry is None:
            return
        nearest = None
        best = 16.0**2
        for point in self._points:
            px, py = self._pixel(*point)
            distance = (px - event.x) ** 2 + (py - event.y) ** 2
            if distance < best:
                best = distance
                nearest = point
        self._set_hover(nearest)

    def _set_hover(self, point: tuple[float, float] | None) -> None:
        if point == self._hover:
            return
        self._hover = point
        self.redraw()

    # -- drawing -------------------------------------------------------
    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        family = font_family(self)
        if width < 90 or height < 80:
            return

        left, right, top, bottom = 58, 18, 40, 38
        plot_w = max(10, width - left - right)
        plot_h = max(10, height - top - bottom)

        if not self._points:
            self.create_text(
                width / 2, height / 2, text=self._empty, fill=MUTED, font=(family, 10)
            )
            return

        xmax = max(x for x, _ in self._points) * 1.15 or 1.0
        ymax = max(y for _, y in self._points) * 1.15 or 1.0
        self._geometry = (left, top, plot_w, plot_h, xmax, ymax)

        xstep = nice_step(xmax, 4)
        ystep = nice_step(ymax, 4)

        value = 0.0
        while value <= xmax + xstep * 0.001:
            x = left + value / xmax * plot_w
            self.create_line(x, top, x, top + plot_h, fill=GRID)
            self.create_text(
                x,
                top + plot_h + 10,
                text=_format_tick(value, xstep),
                fill=MUTED,
                font=(family, 8),
                anchor="n",
            )
            value += xstep

        value = 0.0
        while value <= ymax + ystep * 0.001:
            y = top + (ymax - value) / ymax * plot_h
            self.create_line(left, y, left + plot_w, y, fill=GRID)
            self.create_text(
                left - 8,
                y,
                text=_format_tick(value, ystep),
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )
            value += ystep

        self.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill=BORDER)
        self.create_line(left, top, left, top + plot_h, fill=BORDER)

        if self._slope:
            x_end = min(xmax, ymax / self._slope) if self._slope > 0 else xmax
            self.create_line(
                *self._pixel(0.0, 0.0),
                *self._pixel(x_end, self._slope * x_end),
                fill=ACCENT,
                width=1,
                dash=(5, 4),
            )

        for point in self._points:
            x, y = self._pixel(*point)
            self.create_oval(
                x - 3, y - 3, x + 3, y + 3, fill=SERIES_COLORS["discharge"], outline=""
            )

        if self._highlight:
            x, y = self._pixel(*self._highlight)
            self.create_oval(
                x - 7, y - 7, x + 7, y + 7, outline=SERIES_COLORS["gage"], width=2
            )
            self.create_text(
                x + 10,
                y - 10,
                text="scenario",
                anchor="w",
                fill=SERIES_COLORS["gage"],
                font=(family, 8, "bold"),
            )

        if self._hover:
            x, y = self._pixel(*self._hover)
            self.create_line(x, top, x, top + plot_h, fill=MUTED, dash=(2, 3))
            label = f"{self._hover[0]:.2f} in -> {self._hover[1]:,.0f} cfs"
            box_w = len(label) * 5.4 + 12
            box_x = x + 10 if x + 10 + box_w < width - 6 else x - 10 - box_w
            self.create_rectangle(
                box_x, top + 2, box_x + box_w, top + 20, fill=SURFACE_ALT, outline=BORDER
            )
            self.create_text(
                box_x + 6,
                top + 11,
                text=label,
                anchor="w",
                fill=TEXT,
                font=(family, 8),
            )

        if self._title:
            self.create_text(
                left, 12, text=self._title, anchor="w", fill=TEXT, font=(family, 10, "bold")
            )
        if self._y_unit:
            self.create_text(
                left + plot_w, 12, text=self._y_unit, anchor="e", fill=MUTED, font=(family, 9)
            )
        if self._x_unit:
            self.create_text(
                left + plot_w,
                top + plot_h + 24,
                text=self._x_unit,
                anchor="e",
                fill=MUTED,
                font=(family, 8),
            )
