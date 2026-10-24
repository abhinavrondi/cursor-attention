import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import approve_please as app


class MarkerTests(unittest.TestCase):
    def test_marker_in_new_bytes(self):
        chunk = b'before reason="user-approval-requested" after'
        self.assertGreaterEqual(app.marker_pos(chunk, app.REQUESTED, 0), 0)

    def test_marker_already_in_carry_is_ignored(self):
        carry = b'reason="user-approval-requested"'
        combined = carry + b" more log"
        self.assertEqual(app.marker_pos(combined, app.REQUESTED, len(carry)), -1)

    def test_marker_split_across_carry_counts_once(self):
        needle = app.REQUESTED
        carry = needle[:10]
        chunk = needle[10:]
        combined = carry + chunk
        self.assertEqual(app.marker_pos(combined, needle, len(carry)), 0)
        # The leftover tail is shorter than the marker, so the next poll stays quiet.
        self.assertEqual(
            app.marker_pos(combined[-app.MARKER_TAIL :] + b" idle", needle, app.MARKER_TAIL),
            -1,
        )


class TransitionTests(unittest.TestCase):
    def test_request_starts_a_wait(self):
        pending, event = app.transition(False, 4, -1)
        self.assertEqual((pending, event), (True, "scheduled"))

    def test_resume_clears_a_wait(self):
        pending, event = app.transition(True, -1, 8)
        self.assertEqual((pending, event), (False, "cancelled"))

    def test_resume_without_a_wait_stays_idle(self):
        pending, event = app.transition(False, -1, 8)
        self.assertEqual((pending, event), (False, None))

    def test_resume_after_request_in_the_same_chunk_cancels(self):
        pending, event = app.transition(True, 2, 40)
        self.assertEqual((pending, event), (False, "cancelled"))

    def test_request_after_resume_starts_a_new_wait(self):
        pending, event = app.transition(False, 40, 2)
        self.assertEqual((pending, event), (True, "scheduled"))

    def test_second_request_does_not_reschedule(self):
        pending, event = app.transition(True, 9, -1)
        self.assertEqual((pending, event), (True, None))

    def test_unrelated_bytes_leave_the_wait_alone(self):
        self.assertEqual(app.transition(True, -1, -1), (True, None))
        self.assertEqual(app.transition(False, -1, -1), (False, None))


class GrowthTests(unittest.TestCase):
    def test_equal_size_reads_nothing(self):
        self.assertEqual(app.consume_growth(20, 20), (20, None))

    def test_growth_reads_from_the_old_end(self):
        self.assertEqual(app.consume_growth(30, 20), (30, 20))

    def test_shrink_skips_the_replacement(self):
        self.assertEqual(app.consume_growth(5, 20), (5, None))


class ConfigTests(unittest.TestCase):
    def test_empty_section_uses_defaults(self):
        cfg = app.config_from_mapping({})
        self.assertEqual(cfg.phrase, "Approve please")
        self.assertEqual(cfg.title, "Cursor")
        self.assertEqual(cfg.delay_seconds, 15)
        self.assertEqual(cfg.repeat_seconds, 15)
        self.assertEqual(cfg.poll_seconds, 0.4)
        self.assertTrue(cfg.notify)
        self.assertEqual(cfg.voice, "")
        self.assertEqual(cfg.sound, "")

    def test_overrides(self):
        cfg = app.config_from_mapping(
            {
                "delay_seconds": "20",
                "repeat_seconds": "30",
                "poll_seconds": "1",
                "phrase": "Your turn",
                "title": "Agent",
                "voice": "Samantha",
                "notify": "no",
                "sound": "~/sounds/remind.aiff",
            }
        )
        self.assertEqual(cfg.delay_seconds, 20)
        self.assertEqual(cfg.repeat_seconds, 30)
        self.assertEqual(cfg.phrase, "Your turn")
        self.assertEqual(cfg.voice, "Samantha")
        self.assertFalse(cfg.notify)
        self.assertTrue(cfg.sound.endswith("/sounds/remind.aiff"))

    def test_repeat_floor(self):
        with self.assertRaises(app.ConfigError):
            app.config_from_mapping({"repeat_seconds": "1"})

    def test_empty_phrase(self):
        with self.assertRaises(app.ConfigError):
            app.config_from_mapping({"phrase": ""})

    def test_phrase_with_a_newline(self):
        with self.assertRaises(app.ConfigError):
            app.config_from_mapping({"phrase": "Approve\nplease"})

    def test_bad_notify(self):
        with self.assertRaises(app.ConfigError):
            app.config_from_mapping({"notify": "maybe"})

    def test_load_reads_the_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.ini")
            Path(path).write_text("[approve-please]\nphrase = Ready\n", encoding="utf-8")
            cfg = app.load_config(path)
        self.assertEqual(cfg.phrase, "Ready")
        self.assertEqual(cfg.delay_seconds, 15)

    def test_missing_explicit_file(self):
        with self.assertRaises(app.ConfigError):
            app.load_config("/tmp/cursor-approve-please-missing-config.ini")

    def test_env_path_is_discovered(self):
        previous = os.environ.get(app.ENV_CONFIG)
        os.environ[app.ENV_CONFIG] = "~/settings/approve.ini"
        try:
            self.assertEqual(app.discover_config_path(), os.path.expanduser("~/settings/approve.ini"))
        finally:
            if previous is None:
                os.environ.pop(app.ENV_CONFIG, None)
            else:
                os.environ[app.ENV_CONFIG] = previous


if __name__ == "__main__":
    unittest.main()
