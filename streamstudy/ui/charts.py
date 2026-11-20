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
from .theme import BORDER, GRID, MUTED, SURFACE, SURFACE_ALT, TEXT, font_family


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
            spacing1=1,
        )


def _format_tick(value: float, step: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if step >= 1:
        return f"{value:.0f}"
    if step >= 0.1:
        return f"{value:.1f}"
    return f"{value:.2f}"
