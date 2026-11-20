"""``python -m streamstudy`` entry point."""

from __future__ import annotations

import argparse
import tkinter as tk

from .app import StreamStudyApp
from .providers import build_providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="streamstudy",
        description="Explore USGS stream gages, weather forecasts and precipitation sources.",
    )
    parser.add_argument(
        "--site",
        metavar="NUMBER",
        help="USGS site number to open, e.g. 0423205010",
    )
    parser.add_argument(
        "--days",
        type=int,
        choices=(7, 14, 30, 60),
        help="history window in days",
    )
    parser.add_argument(
        "--settings",
        metavar="PATH",
        help="JSON settings file (default: per-user config directory)",
    )
    args = parser.parse_args(argv)
    return run(site=args.site, days=args.days, settings_path=args.settings)


def run(site: str | None = None, days: int | None = None, settings_path: str | None = None) -> int:
    root = tk.Tk()
    app = StreamStudyApp(
        root, build_providers(), settings_path=settings_path, auto_load=False
    )
    if days is not None:
        app.set_days(days)
    target = site or str(app.settings.get("last_site", "0423205010"))
    root.after(100, lambda: app.load_site(target))
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
