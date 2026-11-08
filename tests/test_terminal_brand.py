"""Brand frames are deterministic artwork, independent of terminal I/O."""
import math
import unittest
import unicodedata

from runtime.terminal_brand import (
    FRAME_SECONDS,
    MARK_HEIGHT,
    MARK_WIDTH,
    STARTING_TEXT,
    TAGLINE,
    frame_form,
    logo_lines,
    splash_lines,
)


def cells(value):
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in value)


class TerminalBrandTests(unittest.TestCase):
    def test_marks_have_fixed_terminal_cell_dimensions_and_no_controls(self):
        for form in ("k", "workflow"):
            for ascii_only in (False, True):
                with self.subTest(form=form, ascii_only=ascii_only):
                    rows = logo_lines(form, ascii_only=ascii_only)
                    self.assertIsInstance(rows, tuple)
                    self.assertEqual(len(rows), MARK_HEIGHT)
                    self.assertTrue(all(cells(row) == MARK_WIDTH for row in rows))
                    self.assertTrue(all(unicodedata.category(char) not in {"Cc", "Cf"} for row in rows for char in row))
                    if ascii_only:
                        self.assertTrue("".join(rows).isascii())
        self.assertNotEqual(logo_lines("k"), logo_lines("workflow"))
        self.assertEqual(sum(row.count("○") for row in logo_lines("workflow")), 3)

    def test_animation_alternates_only_while_work_is_active(self):
        for seconds in (0, 0.4, 0.8, 1.5, 1.6, 120.7):
            self.assertEqual(frame_form(False, seconds), "k")
        self.assertEqual(frame_form(True, 0), "k")
        self.assertEqual(frame_form(True, FRAME_SECONDS - 0.01), "k")
        self.assertEqual(frame_form(True, FRAME_SECONDS), "workflow")
        self.assertEqual(frame_form(True, FRAME_SECONDS * 2), "k")
        self.assertEqual(frame_form(True, FRAME_SECONDS * 3 + 0.01), "workflow")
        for invalid in (-1, math.inf, -math.inf, math.nan, None, "invalid"):
            self.assertEqual(frame_form(True, invalid), "k")

    def test_normal_splash_has_brand_and_caption_centered_without_escape_codes(self):
        for ascii_only in (False, True):
            output = splash_lines(100, 32, ascii_only=ascii_only)
            lines = output.splitlines()
            self.assertLessEqual(len(lines), 32)
            self.assertTrue(all(cells(line) <= 100 for line in lines))
            self.assertIn(TAGLINE, output)
            self.assertIn(STARTING_TEXT, output)
            self.assertEqual(lines[0], "")
            self.assertNotIn("\x1b", output)
            self.assertTrue(all(not line.endswith(" ") for line in lines))
            self.assertEqual(next(line for line in lines if TAGLINE in line).index(TAGLINE), (100 - len(TAGLINE)) // 2)
            if ascii_only:
                self.assertTrue(output.isascii())

    def test_small_screens_always_remain_within_available_cells(self):
        for width in (1, 3, 4, 10, 11, 25, 31, 40, 45, 46, 80):
            for height in (1, 3, 5, 6, 7, 8, 12):
                for ascii_only in (False, True):
                    with self.subTest(width=width, height=height, ascii_only=ascii_only):
                        output = splash_lines(width, height, ascii_only)
                        self.assertLessEqual(len(output.splitlines()), height)
                        self.assertTrue(all(cells(line) <= width for line in output.splitlines()))
                        self.assertTrue(output.strip())
        self.assertEqual(splash_lines(4, 1), "KNOT")
        self.assertEqual(splash_lines(0, 10), "")
        self.assertEqual(splash_lines(10, 0), "")
        self.assertEqual(splash_lines(-1, 10), "")

    def test_unknown_artwork_name_is_rejected(self):
        with self.assertRaises(ValueError):
            logo_lines("unknown")


if __name__ == "__main__":
    unittest.main()
