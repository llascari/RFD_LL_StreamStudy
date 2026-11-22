"""Generate a historical PDF report, with visible progress for slow jobs.

A region report fetches one USGS daily-values series and one Open-Meteo archive
per gage, so it can take minutes. The dialog runs the work on a worker thread,
shows the current site and attempt, warns when nothing has moved for a while,
and lets the user cancel between sites.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..analysis_window import (
    CUSTOM_LABEL,
    LABEL_TO_KEY,
    PRESET_BY_KEY,
    PRESET_LABELS,
    key_for_window,
    parse_custom,
    preset_window,
)
from ..loader import ReportCancelled
from ..report import write_report


class ReportDialog(tk.Toplevel):
    """Modal dialog for a single-gage or radius PDF report."""

    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Generate PDF report")
        self.resizable(False, False)
        self.transient(app.root)
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._running = False
        self._last_activity = time.monotonic()
        self._started = time.monotonic()
        self._poll_id: str | None = None
        self._output: Path | None = None
        self._last_message = "Ready"

        site = app.bundle.site if app.bundle is not None else None
        if site is None:
            messagebox.showwarning(
                "StreamStudy",
                "Load a USGS site before generating a report.",
                parent=app.root,
            )
            self.destroy()
            return
        self.site = site
        self._build()
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # -- construction ---------------------------------------------------
    def _build(self) -> None:
        frame = ttk.Frame(self, padding=(18, 16))
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text=f"Historical report for {self.site.name}",
            style="Heading.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text=(
                f"USGS {self.site.number}  |  up to 10 years of daily flow and temperature, "
                "with maps, charts, extremes, sources and limitations."
            ),
            style="Muted.TLabel",
            wraplength=620,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))

        ttk.Label(frame, text="History window").grid(row=2, column=0, sticky="w", pady=4)
        current_key = key_for_window(self.app.analysis_window)
        default_label = (
            PRESET_BY_KEY[current_key][0] if current_key is not None else CUSTOM_LABEL
        )
        self.window_var = tk.StringVar(value=default_label)
        self.window_box = ttk.Combobox(
            frame,
            textvariable=self.window_var,
            values=PRESET_LABELS + [CUSTOM_LABEL],
            state="readonly",
            width=22,
        )
        self.window_box.grid(row=2, column=1, sticky="w", pady=4)
        self.window_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._sync_window_fields()
        )

        self.start_var = tk.StringVar(value=self.app.analysis_window.start.isoformat())
        self.end_var = tk.StringVar(value=self.app.analysis_window.end.isoformat())
        custom = ttk.Frame(frame)
        custom.grid(row=3, column=1, sticky="w", pady=(0, 4))
        ttk.Label(custom, text="from").pack(side="left")
        self.start_entry = ttk.Entry(custom, textvariable=self.start_var, width=12)
        self.start_entry.pack(side="left", padx=4)
        ttk.Label(custom, text="to").pack(side="left")
        self.end_entry = ttk.Entry(custom, textvariable=self.end_var, width=12)
        self.end_entry.pack(side="left", padx=4)
        ttk.Label(custom, text="(YYYY-MM-DD)").pack(side="left", padx=(2, 0))

        ttk.Label(frame, text="Nearby region").grid(row=4, column=0, sticky="w", pady=4)
        region_row = ttk.Frame(frame)
        region_row.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)
        self.region_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            region_row,
            text="Include gages within",
            variable=self.region_var,
            command=self._sync_region_fields,
        ).pack(side="left")
        self.radius_var = tk.StringVar(value="10")
        self.radius_spin = ttk.Spinbox(
            region_row,
            from_=1,
            to=100,
            increment=1,
            width=6,
            textvariable=self.radius_var,
        )
        self.radius_spin.pack(side="left", padx=(4, 2))
        ttk.Label(region_row, text="km, at most").pack(side="left")
        self.max_sites_var = tk.StringVar(value="6")
        self.max_sites_spin = ttk.Spinbox(
            region_row,
            from_=1,
            to=12,
            increment=1,
            width=5,
            textvariable=self.max_sites_var,
        )
        self.max_sites_spin.pack(side="left", padx=(4, 2))
        ttk.Label(region_row, text="sites").pack(side="left")

        ttk.Label(frame, text="Temperature threshold").grid(
            row=5, column=0, sticky="w", pady=4
        )
        threshold_row = ttk.Frame(frame)
        threshold_row.grid(row=5, column=1, columnspan=2, sticky="w", pady=4)
        self.threshold_var = tk.StringVar(value=f"{self.app.temperature_threshold:g}")
        ttk.Spinbox(
            threshold_row,
            from_=0,
            to=40,
            increment=0.5,
            width=6,
            textvariable=self.threshold_var,
        ).pack(side="left")
        ttk.Label(
            threshold_row, text="C  (also used by the Temperature tab)"
        ).pack(side="left", padx=(4, 0))

        ttk.Label(frame, text="PDF file").grid(row=6, column=0, sticky="w", pady=4)
        default_name = (
            f"StreamStudy_{self.site.number}_"
            f"{self.app.analysis_window.start.isoformat()}_"
            f"{self.app.analysis_window.end.isoformat()}.pdf"
        )
        self.path_var = tk.StringVar(value=str(Path.home() / default_name))
        path_row = ttk.Frame(frame)
        path_row.grid(row=6, column=1, columnspan=2, sticky="ew", pady=4)
        path_row.columnconfigure(0, weight=1)
        ttk.Entry(path_row, textvariable=self.path_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(path_row, text="Browse\u2026", command=self._browse).grid(
            row=0, column=1, padx=(6, 0)
        )

        ttk.Label(
            frame,
            text=(
                "The full daily record is fetched from USGS and Open-Meteo. A region report "
                "loads one site at a time with two retries each, so give it a few minutes on a "
                "slow connection. Cancel is checked between sites."
            ),
            style="Muted.TLabel",
            wraplength=620,
            justify="left",
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 8))

        self.progress = ttk.Progressbar(
            frame, mode="determinate", maximum=100, length=430
        )
        self.progress.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(
            frame,
            textvariable=self.progress_var,
            style="Muted.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=9, column=0, columnspan=3, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)
        self.open_button = ttk.Button(
            buttons, text="Open report", command=self._open_report, state="disabled"
        )
        self.open_button.grid(row=0, column=0, sticky="w")
        self.cancel_button = ttk.Button(
            buttons,
            text="Cancel",
            command=self._request_cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 6))
        self.generate_button = ttk.Button(
            buttons, text="Generate", style="Accent.TButton", command=self._start
        )
        self.generate_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Button(buttons, text="Close", command=self._on_close).grid(row=0, column=3)

        self._sync_window_fields()
        self._sync_region_fields()

    # -- field behaviour ------------------------------------------------
    def _sync_window_fields(self) -> None:
        custom = self.window_var.get() == CUSTOM_LABEL
        state = "normal" if custom else "disabled"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)
        if not custom:
            key = LABEL_TO_KEY.get(self.window_var.get(), "1y")
            window = preset_window(key)
            self.start_var.set(window.start.isoformat())
            self.end_var.set(window.end.isoformat())

    def _sync_region_fields(self) -> None:
        state = "normal" if self.region_var.get() else "disabled"
        self.radius_spin.configure(state=state)
        self.max_sites_spin.configure(state=state)

    def _browse(self) -> None:
        name = filedialog.asksaveasfilename(
            parent=self,
            title="Save report as",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=Path(self.path_var.get()).name,
        )
        if name:
            self.path_var.set(name)

    # -- running --------------------------------------------------------
    def _start(self) -> None:
        if self._running:
            return
        try:
            if self.window_var.get() == CUSTOM_LABEL:
                window = parse_custom(self.start_var.get(), self.end_var.get())
            else:
                window = preset_window(LABEL_TO_KEY.get(self.window_var.get(), "1y"))
            radius = float(self.radius_var.get())
            max_sites = int(float(self.max_sites_var.get()))
            threshold = float(self.threshold_var.get())
            path = Path(self.path_var.get()).expanduser()
        except ValueError as exc:
            messagebox.showwarning(
                "StreamStudy", f"Check the report fields: {exc}", parent=self
            )
            return
        if not str(path):
            messagebox.showwarning(
                "StreamStudy", "Choose an output PDF file.", parent=self
            )
            return
        include_region = bool(self.region_var.get())
        if abs(threshold - self.app.temperature_threshold) > 1e-9:
            self.app.set_temperature_threshold(threshold)
        self._output = path
        self._cancel.clear()
        self._running = True
        self._started = self._last_activity = time.monotonic()
        self.progress.configure(mode="determinate", value=0)
        self._last_message = "Starting\u2026"
        self.progress_var.set(self._last_message)
        self.generate_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")

        app = self.app
        site = self.site
        coco = (
            app.bundle.coco_station.identifier
            if app.bundle is not None and app.bundle.coco_station is not None
            else None
        )
        report_queue = self._queue

        def progress(fraction: float, message: str) -> None:
            report_queue.put(("progress", fraction, message))

        def work() -> None:
            try:
                data = app.loader.load_report_region(
                    site,
                    window,
                    radius_km=radius,
                    include_region=include_region,
                    max_sites=max_sites,
                    threshold_c=threshold,
                    coco_station=coco,
                    retries=2,
                    delay=1.0,
                    progress=progress,
                    cancel=self._cancel.is_set,
                )
                report_queue.put(("writing", 1.0, "Writing the PDF"))
                written = write_report(data, path)
                report_queue.put(("done", written, data))
            except ReportCancelled:
                report_queue.put(("cancelled", None, None))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                report_queue.put(("error", exc, None))

        threading.Thread(target=work, daemon=True).start()

    def _request_cancel(self) -> None:
        self._cancel.set()
        self.cancel_button.configure(state="disabled")
        self.progress_var.set("Cancelling after the current site\u2026")

    def _poll(self) -> None:
        if not self.winfo_exists():
            return

        def drain() -> None:
            try:
                while True:
                    kind, value, extra = self._queue.get_nowait()
                    self._last_activity = time.monotonic()
                    if kind == "progress":
                        self.progress.configure(value=100.0 * float(value))
                        self._last_message = str(extra)
                        self.progress_var.set(self._last_message)
                    elif kind == "writing":
                        self.progress.configure(value=100)
                        self._last_message = "Writing the PDF\u2026"
                        self.progress_var.set(self._last_message)
                    elif kind == "done":
                        self._finish_done(value, extra)
                    elif kind == "cancelled":
                        self._finish_cancelled()
                    elif kind == "error":
                        self._finish_error(value)
            except queue.Empty:
                pass

        drain()
        if self._running:
            now = time.monotonic()
            quiet = now - self._last_activity
            elapsed = now - self._started
            if quiet > 20:
                self.progress_var.set(
                    f"{self._last_message}  \u2014  no new data for {quiet:.0f} s; "
                    f"elapsed {elapsed:.0f} s. Network sources can be slow."
                )
            elif quiet > 8:
                self.progress_var.set(
                    f"{self._last_message}  (still working, {elapsed:.0f} s elapsed)"
                )
            self._poll_id = self.after(250, self._poll)
        else:
            self._poll_id = None

    def _finish_done(self, path, data) -> None:
        self._running = False
        self.progress.configure(value=100)
        loaded = 1 + len(getattr(data, "region", ()))
        failures = len(getattr(data, "failures", ()))
        text = f"Report written to {path}  |  {loaded} site(s)"
        if failures:
            text += f"  |  {failures} site(s) skipped (see report)"
        self._last_message = text
        self.progress_var.set(text)
        self.open_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.generate_button.configure(state="normal")
        self._output = Path(path)

    def _finish_cancelled(self) -> None:
        self._running = False
        self.progress_var.set("Cancelled. No report was written.")
        self.cancel_button.configure(state="disabled")
        self.generate_button.configure(state="normal")

    def _finish_error(self, error) -> None:
        self._running = False
        self.progress_var.set("Report failed.")
        self.cancel_button.configure(state="disabled")
        self.generate_button.configure(state="normal")
        messagebox.showerror(
            "StreamStudy",
            f"The report could not be generated:\n\n{error}\n\n"
            "Try a shorter window, a smaller radius, or retry when the network is stable.",
            parent=self,
        )

    def _open_report(self) -> None:
        if self._output is None or not Path(self._output).exists():
            messagebox.showinfo(
                "StreamStudy", "The PDF is not on disk any more.", parent=self
            )
            return
        webbrowser.open(Path(self._output).resolve().as_uri())

    # -- closing --------------------------------------------------------
    def _on_close(self) -> None:
        if self._running:
            stop = messagebox.askyesno(
                "StreamStudy",
                "A report is still being generated. Stop after the current site?",
                parent=self,
            )
            if not stop:
                return
            self._cancel.set()
        self._running = False
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._poll_id = None
        try:
            self.grab_release()
        except tk.TclError:  # pragma: no cover
            pass
        self.destroy()
