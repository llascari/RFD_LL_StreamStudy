import unittest

from focusdeck.engine import Phase, PomodoroEngine, Settings, format_seconds


class FormatSecondsTest(unittest.TestCase):
    def test_padding(self):
        self.assertEqual(format_seconds(0), "00:00")
        self.assertEqual(format_seconds(59), "00:59")
        self.assertEqual(format_seconds(1500), "25:00")
        self.assertEqual(format_seconds(3599), "59:59")

    def test_rounds_up_and_clamps(self):
        self.assertEqual(format_seconds(0.2), "00:01")
        self.assertEqual(format_seconds(-5), "00:00")


class SettingsTest(unittest.TestCase):
    def test_validation_clamps_out_of_range_values(self):
        settings = Settings(
            focus_minutes=0,
            short_break_minutes=999,
            sessions_until_long_break=0,
            daily_goal_minutes=1,
        ).validated()
        self.assertEqual(settings.focus_minutes, 1)
        self.assertEqual(settings.short_break_minutes, 60)
        self.assertEqual(settings.sessions_until_long_break, 1)
        self.assertEqual(settings.daily_goal_minutes, 15)

    def test_roundtrip(self):
        settings = Settings(focus_minutes=50, auto_start_focus=True)
        self.assertEqual(Settings.from_dict(settings.to_dict()), settings)

    def test_from_dict_falls_back_to_defaults(self):
        self.assertEqual(Settings.from_dict({}), Settings())
        self.assertEqual(Settings.from_dict(None), Settings())
        self.assertEqual(Settings.from_dict({"focus_minutes": "nope"}), Settings())
        self.assertEqual(
            Settings.from_dict({"daily_goal_minutes": 99999}).daily_goal_minutes, 960
        )


class EngineTest(unittest.TestCase):
    def make(self, **kwargs) -> PomodoroEngine:
        return PomodoroEngine(Settings(**kwargs))

    def test_initial_state(self):
        engine = self.make()
        self.assertEqual(engine.phase, Phase.FOCUS)
        self.assertEqual(engine.remaining_seconds, 1500)
        self.assertEqual(engine.total_seconds, 1500)
        self.assertFalse(engine.running)
        self.assertEqual(engine.progress, 0.0)

    def test_advance_does_nothing_while_paused(self):
        engine = self.make()
        self.assertEqual(engine.advance(10), ())
        self.assertEqual(engine.remaining_seconds, 1500)

    def test_countdown_and_pause(self):
        engine = self.make()
        engine.start()
        self.assertTrue(engine.running)
        engine.advance(60)
        self.assertEqual(engine.remaining_seconds, 1440)
        engine.pause()
        engine.advance(30)
        self.assertEqual(engine.remaining_seconds, 1440)

    def test_toggle(self):
        engine = self.make()
        engine.toggle()
        self.assertTrue(engine.running)
        engine.toggle()
        self.assertFalse(engine.running)

    def test_focus_completion_enters_short_break(self):
        engine = self.make(focus_minutes=1, short_break_minutes=1)
        engine.start()
        completed = engine.advance(60)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].phase, Phase.FOCUS)
        self.assertEqual(completed[0].duration_seconds, 60)
        self.assertEqual(engine.phase, Phase.SHORT_BREAK)
        self.assertTrue(engine.running)  # auto_start_breaks defaults to True
        self.assertEqual(engine.remaining_seconds, 60)
        self.assertEqual(engine.completed_focus_sessions, 1)

    def test_break_does_not_auto_start_focus_by_default(self):
        engine = self.make(focus_minutes=1, short_break_minutes=1)
        engine.start()
        engine.advance(60)  # break begins
        engine.advance(60)  # break ends
        self.assertEqual(engine.phase, Phase.FOCUS)
        self.assertFalse(engine.running)
        self.assertEqual(engine.remaining_seconds, 60)

    def test_leftover_time_spills_over(self):
        engine = self.make(focus_minutes=1, short_break_minutes=1)
        engine.start()
        completed = engine.advance(90)
        self.assertEqual([c.phase for c in completed], [Phase.FOCUS])
        self.assertEqual(engine.phase, Phase.SHORT_BREAK)
        self.assertEqual(engine.remaining_seconds, 30)

    def test_long_break_after_configured_focus_sessions(self):
        engine = self.make(
            focus_minutes=1,
            short_break_minutes=1,
            long_break_minutes=2,
            sessions_until_long_break=4,
        )
        engine.start()
        phases = []
        for _ in range(4):
            engine.advance(60)  # finish focus
            phases.append(engine.phase)
            engine.advance(60)  # finish the break
            engine.start()  # begin next focus block
        self.assertEqual(
            phases,
            [Phase.SHORT_BREAK, Phase.SHORT_BREAK, Phase.SHORT_BREAK, Phase.LONG_BREAK],
        )
        self.assertEqual(engine.completed_focus_sessions, 4)

    def test_skip_moves_on_without_counting_a_session(self):
        engine = self.make()
        engine.start()
        engine.advance(30)
        engine.skip()
        self.assertEqual(engine.completed_focus_sessions, 0)
        self.assertEqual(engine.phase, Phase.SHORT_BREAK)
        self.assertEqual(engine.remaining_seconds, 300)
        self.assertTrue(engine.running)  # breaks auto-start by default

        engine.skip()  # skipping a break returns to focus
        self.assertEqual(engine.phase, Phase.FOCUS)
        self.assertEqual(engine.remaining_seconds, 1500)
        self.assertFalse(engine.running)

    def test_reset_refills_the_current_phase(self):
        engine = self.make()
        engine.start()
        engine.advance(100)
        engine.reset()
        self.assertFalse(engine.running)
        self.assertEqual(engine.remaining_seconds, 1500)

    def test_apply_settings_while_paused_restarts_the_phase(self):
        engine = self.make()
        engine.advance(100)
        engine.apply_settings(Settings(focus_minutes=50))
        self.assertEqual(engine.total_seconds, 3000)
        self.assertEqual(engine.remaining_seconds, 3000)

    def test_apply_settings_while_running_keeps_elapsed_time(self):
        engine = self.make()
        engine.start()
        engine.advance(300)
        engine.apply_settings(Settings(focus_minutes=50))
        self.assertEqual(engine.total_seconds, 3000)
        self.assertEqual(engine.remaining_seconds, 2700)

    def test_progress(self):
        engine = self.make()
        engine.start()
        engine.advance(750)
        self.assertAlmostEqual(engine.progress, 0.5)


if __name__ == "__main__":
    unittest.main()
