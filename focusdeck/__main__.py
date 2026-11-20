"""``python -m focusdeck`` entry point."""

from __future__ import annotations

import argparse

from .app import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="focusdeck",
        description="FocusDeck - a small Pomodoro-style focus timer.",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="SQLite database file (default: the per-user application data folder, "
        "or $FOCUSDECK_DB)",
    )
    args = parser.parse_args(argv)
    return run(db_path=args.db)


if __name__ == "__main__":
    raise SystemExit(main())
