"""The Pomodoro state machine.

This module is deliberately free of GUI and I/O code: it is pure logic so it
can be unit tested and reused by other front ends.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

_PHASE_LABELS = {
    "focus": "Focus",
    "short_break": "Short break",
    "long_break": "Long break",
}


class Phase(str, Enum):
    """The three kinds of interval a session cycles through."""

    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"

    @property
    def label(self) -> str:
        return _PHASE_LABELS[self.value]


def format_seconds(seconds: float) -> str:
    """Format a duration as ``MM:SS``.

    Rounds up, so a timer with 0.2 s left shows ``00:01`` instead of ``00:00``.
    """
    total = max(0, math.ceil(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class Settings:
    """User-configurable timer preferences."""

    focus_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    sessions_until_long_break: int = 4
    daily_goal_minutes: int = 120
    auto_start_breaks: bool = True
    auto_start_focus: bool = False

    def validated(self) -> "Settings":
        """Return a copy with every value clamped to a sensible range."""

        def clamp(value: object, low: int, high: int) -> int:
            return max(low, min(int(value), high))  # type: ignore[arg-type]

        return replace(
            self,
            focus_minutes=clamp(self.focus_minutes, 1, 180),
            short_break_minutes=clamp(self.short_break_minutes, 1, 60),
            long_break_minutes=clamp(self.long_break_minutes, 1, 120),
            sessions_until_long_break=clamp(self.sessions_until_long_break, 1, 12),
            daily_goal_minutes=clamp(self.daily_goal_minutes, 15, 960),
            auto_start_breaks=bool(self.auto_start_breaks),
            auto_start_focus=bool(self.auto_start_focus),
        )

    def to_dict(self) -> dict:
        return {
            "focus_minutes": self.focus_minutes,
            "short_break_minutes": self.short_break_minutes,
            "long_break_minutes": self.long_break_minutes,
            "sessions_until_long_break": self.sessions_until_long_break,
            "daily_goal_minutes": self.daily_goal_minutes,
            "auto_start_breaks": self.auto_start_breaks,
            "auto_start_focus": self.auto_start_focus,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        """Build settings from a stored dict, falling back to defaults."""
        defaults = cls()
        data = data or {}

        def get(key: str):
            return data.get(key, getattr(defaults, key))

        try:
            return cls(
                focus_minutes=int(get("focus_minutes")),
                short_break_minutes=int(get("short_break_minutes")),
                long_break_minutes=int(get("long_break_minutes")),
                sessions_until_long_break=int(get("sessions_until_long_break")),
                daily_goal_minutes=int(get("daily_goal_minutes")),
                auto_start_breaks=bool(get("auto_start_breaks")),
                auto_start_focus=bool(get("auto_start_focus")),
            ).validated()
        except (TypeError, ValueError):
            return defaults


@dataclass(frozen=True)
class PhaseCompleted:
    """Emitted when a phase runs all the way down to zero."""

    phase: Phase
    duration_seconds: int


class PomodoroEngine:
    """A ticking interval timer that alternates focus and break phases."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = (settings or Settings()).validated()
        self.phase = Phase.FOCUS
        self.completed_focus_sessions = 0
        self._running = False
        self._total = float(self.duration_for(self.phase))
        self._remaining = self._total

    # -- introspection -------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def running(self) -> bool:
        return self._running

    @property
    def remaining_seconds(self) -> float:
        return self._remaining

    @property
    def total_seconds(self) -> int:
        return int(self._total)

    @property
    def progress(self) -> float:
        """Elapsed fraction of the current phase, in the range 0.0-1.0."""
        if self._total <= 0:
            return 0.0
        return min(1.0, max(0.0, 1.0 - self._remaining / self._total))

    def duration_for(self, phase: Phase) -> int:
        """Length of the given phase in seconds under the current settings."""
        minutes = {
            Phase.FOCUS: self._settings.focus_minutes,
            Phase.SHORT_BREAK: self._settings.short_break_minutes,
            Phase.LONG_BREAK: self._settings.long_break_minutes,
        }[phase]
        return int(minutes) * 60

    # -- controls ------------------------------------------------------
    def start(self) -> None:
        if self._remaining <= 0:
            self.reset()
        self._running = True

    def pause(self) -> None:
        self._running = False

    def toggle(self) -> None:
        if self._running:
            self.pause()
        else:
            self.start()

    def reset(self) -> None:
        """Stop the clock and refill the current phase."""
        self._running = False
        self._total = float(self.duration_for(self.phase))
        self._remaining = self._total

    def skip(self) -> None:
        """Abandon the current phase and move on without recording it.

        A skipped focus block does not count toward the long-break cycle; you
        always land on a short break (or back on focus, from a break).
        """
        if self.phase is Phase.FOCUS:
            self._set_phase(
                Phase.SHORT_BREAK, running=self._settings.auto_start_breaks
            )
        else:
            self._set_phase(Phase.FOCUS, running=self._settings.auto_start_focus)

    def advance(self, seconds: float) -> tuple[PhaseCompleted, ...]:
        """Move the clock forward, returning any phases that finished.

        Leftover time spills into the next phase when auto-start is on, so a
        coarse tick (say 1.5 s covering a phase boundary) still stays accurate.
        """
        if not self._running or seconds <= 0 or self._total <= 0:
            return ()

        leftover = float(seconds)
        completed: list[PhaseCompleted] = []
        while leftover > 0 and self._running:
            if leftover < self._remaining:
                self._remaining -= leftover
                break
            leftover -= self._remaining
            completed.append(PhaseCompleted(self.phase, int(self._total)))
            self._enter_next()
        return tuple(completed)

    def apply_settings(self, settings: Settings) -> None:
        """Adopt new settings, preserving elapsed time where it makes sense."""
        old_total = self._total
        self._settings = settings.validated()
        new_total = float(self.duration_for(self.phase))
        if self._running and old_total > 0:
            elapsed = max(0.0, old_total - self._remaining)
            self._total = max(1.0, new_total)
            self._remaining = max(0.0, self._total - elapsed)
        else:
            self._total = new_total
            self._remaining = new_total

    # -- internals -----------------------------------------------------
    def _enter_next(self) -> None:
        if self.phase is Phase.FOCUS:
            self.completed_focus_sessions += 1
            every = max(1, self._settings.sessions_until_long_break)
            is_long = self.completed_focus_sessions % every == 0
            self._set_phase(
                Phase.LONG_BREAK if is_long else Phase.SHORT_BREAK,
                running=self._settings.auto_start_breaks,
            )
        else:
            self._set_phase(Phase.FOCUS, running=self._settings.auto_start_focus)

    def _set_phase(self, phase: Phase, *, running: bool) -> None:
        self.phase = phase
        self._total = float(self.duration_for(phase))
        self._remaining = self._total
        self._running = running
