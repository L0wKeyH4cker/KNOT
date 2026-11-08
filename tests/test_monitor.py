"""Terminal display and navigation behavior; never starts a model or workflow."""
from __future__ import annotations

import copy
import io
import re
import threading
import unittest
from unittest.mock import patch

from runtime.monitor import _Terminal, _ascii_output, _key_name, cell_width, clip, colorize_frame, render_dashboard, watch as runtime_watch
from runtime.terminal_brand import logo_lines


def watch(*args, **kwargs):
    kwargs.setdefault("splash", False)
    return runtime_watch(*args, **kwargs)

NOW = 1794096000.0


def sample(run_id="one", project="Campus project"):
    return {
        "run_id": run_id, "root": "C:/Work/Campus", "project": {"name": project},
        "status": "running", "live": True, "started_at": NOW - 120, "updated_at": NOW,
        "heartbeat_at": NOW, "execution": {"backend": "codex", "model": ""},
        "nodes": {
            "start": {"type": "start", "label": "Start", "status": "succeeded"},
            "left": {"type": "agent_task", "label": "Build frontend", "agent_name": "UI engineer",
                     "status": "succeeded", "started_at": NOW - 110, "finished_at": NOW - 30,
                     "activity": {"kind": "file", "text": "Updated src/App.tsx"},
                     "last_activity_at": NOW - 30},
            "right": {"type": "agent_task", "label": "Build backend", "agent_name": "API engineer",
                      "status": "running", "started_at": NOW - 100,
                      "activity": {"kind": "command", "text": "python -m unittest", "status": "running"},
                      "last_activity_at": NOW - 5},
            "join": {"type": "agent_task", "label": "Integration", "agent_name": "Reviewer",
                     "status": "pending"},
        },
        "last_events": [{"time": NOW - 5, "node_id": "right", "event": "coding_event",
                         "activity": {"kind": "command", "text": "python -m unittest"}}],
    }


class FakeTerminal:
    def __init__(self, keys=(), enabled=True, on_draw=None):
        self.enabled = enabled
        self.keys = iter(keys)
        self.frames = []
        self.exited = False
        self.on_draw = on_draw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.exited = True

    def size(self):
        return 100, 32

    def draw(self, frame):
        self.frames.append(frame)
        if self.on_draw:
            self.on_draw()

    def key(self):
        return next(self.keys, "quit")


class MonitorRenderTests(unittest.TestCase):
    def test_only_live_running_workflows_animate_the_top_right_mark(self):
        run = sample()
        for elapsed, expected in ((0, "k"), (.9, "workflow"), (1.7, "k")):
            with self.subTest(elapsed=elapsed):
                frame = render_dashboard([run], now=NOW, animation_elapsed=elapsed, ascii_only=True)
                self.assertEqual([line[-11:] for line in frame.splitlines()[:5]], list(logo_lines(expected, True)))
                self.assertNotIn("\x1b", frame)
        for status, live in (("completed", True), ("failed", True), ("waiting_review", True),
                             ("pending", True), ("running", False), ("running", None)):
            with self.subTest(status=status, live=live):
                run.update(status=status, live=live)
                frame = render_dashboard([run], now=NOW, animation_elapsed=.9, ascii_only=True)
                self.assertEqual([line[-11:] for line in frame.splitlines()[:5]], list(logo_lines("k", True)))

    def test_multiple_projects_animate_while_any_live_workflow_runs(self):
        idle = sample("idle")
        idle.update(status="completed", live=False)
        frame = render_dashboard([idle, sample()], now=NOW, animation_elapsed=.9, ascii_only=True)
        self.assertEqual([line[-11:] for line in frame.splitlines()[:5]], list(logo_lines("workflow", True)))

    def test_colors_are_separate_and_no_color_keeps_plain_art(self):
        frame = render_dashboard([sample()], now=NOW, ascii_only=True)
        with patch("runtime.monitor.os.environ", {}):
            styled = colorize_frame(frame)
            self.assertIn("\x1b[", styled)
            self.assertEqual(re.sub(r"\x1b\[[0-9;]*m", "", styled), frame)
        with patch.dict("runtime.monitor.os.environ", {"NO_COLOR": ""}):
            self.assertEqual(colorize_frame(frame), frame)
            self.assertIn(logo_lines("k", True)[0], frame)
        self.assertFalse(any(line and set(line) == {"-"} for line in frame.splitlines()))

    def test_reduced_motion_keeps_fixed_k(self):
        with patch.dict("runtime.monitor.os.environ", {"KNOT_NO_ANIMATION": "1"}):
            frame = render_dashboard([sample()], now=NOW, animation_elapsed=.9, ascii_only=True)
        self.assertEqual([line[-11:] for line in frame.splitlines()[:5]], list(logo_lines("k", True)))

    def test_non_unicode_stream_uses_ascii_art(self):
        class Stream:
            encoding = "ascii"
        self.assertTrue(_ascii_output(Stream()))
        Stream.encoding = "gbk"
        self.assertTrue(_ascii_output(Stream()))
        Stream.encoding = "utf-8"
        self.assertFalse(_ascii_output(Stream()))

    def test_real_task_counts_do_not_count_control_nodes_or_invent_percentages(self):
        frame = render_dashboard([sample()], selected_task=1, now=NOW)
        self.assertIn("1/3 agent tasks done", frame)
        self.assertIn("UI engineer", frame)
        self.assertIn("API engineer", frame)
        self.assertIn("python -m unittest", frame)
        self.assertIn("last activity 5s ago", frame)
        self.assertNotIn("%", frame)

    def test_chinese_labels_and_controls_fit_narrow_and_normal_terminals(self):
        run = sample(project="校园出行项目" * 10)
        run["nodes"]["right"]["label"] = "实现后端接口" * 10
        run["nodes"]["right"]["activity"]["text"] = "检查中文路径" * 30
        for width, height in ((20, 10), (40, 12), (68, 23), (80, 24), (100, 32), (160, 50)):
            with self.subTest(width=width, height=height):
                frame = render_dashboard([run], selected_task=1, width=width, height=height, now=NOW)
                self.assertLessEqual(len(frame.splitlines()), height)
                self.assertTrue(all(cell_width(line) <= width for line in frame.splitlines()))
                self.assertIn("q", frame.splitlines()[-1])

    def test_alignment_is_kept_after_sanitization(self):
        frame = render_dashboard([sample()], now=NOW)
        row = next(line for line in frame.splitlines() if "UI engineer" in line)
        self.assertIn("  ", row)
        self.assertEqual(cell_width(clip("中文字体", 7)), 7)
        self.assertLessEqual(cell_width(clip("e\u0301中文", 4)), 4)

    def test_stale_heartbeat_does_not_claim_an_agent_is_still_running(self):
        run = sample()
        run.update(live=False, display_status="disconnected", heartbeat_at=NOW - 40)
        frame = render_dashboard([run], selected_task=1, now=NOW)
        self.assertIn("OFFLINE", frame)
        self.assertIn("last saved state", frame)
        self.assertNotIn("RUNNING", frame)
        self.assertIn("1m 00s", frame)

    def test_paused_review_is_not_offline_when_the_runner_has_exited(self):
        run = sample()
        run.update(status="waiting_review", live=False)
        frame = render_dashboard([run], now=NOW)
        self.assertIn("REVIEW NEEDED", frame)
        self.assertIn("read-only", frame)
        self.assertNotIn("OFFLINE", frame)

    def test_terminal_control_sequences_and_credentials_are_never_rendered(self):
        run = sample(project="Project\x1b[2J\x1b]0;fake-title\x07")
        run["nodes"]["right"]["activity"]["text"] = "curl -H 'Authorization: Bearer sensitive-token-123456' /api"
        run["nodes"]["right"]["error"] = "API_KEY=do-not-display\x1b[?25l"
        frame = render_dashboard([run], selected_task=1, now=NOW)
        self.assertNotIn("\x1b", frame)
        self.assertNotIn("\x07", frame)
        self.assertNotIn("sensitive-token-123456", frame)
        self.assertNotIn("do-not-display", frame)

    def test_empty_legacy_or_malformed_optional_metadata_is_readable(self):
        empty = render_dashboard([], now=NOW)
        self.assertIn("No local workflows", empty)
        self.assertIn("--root", empty)
        run = {"run_id": "old", "status": "completed", "project": None, "nodes": None, "events": None}
        frame = render_dashboard([None, run], selected_run=99, selected_task=99, now=NOW)
        self.assertIn("DONE", frame)
        self.assertIn("No agent-task metadata", frame)


class MonitorInteractionTests(unittest.TestCase):
    def test_non_tty_outputs_one_snapshot_without_ansi_or_waiting(self):
        output = io.StringIO()
        with patch("runtime.monitor._show_splash") as splash:
            result = watch(lambda: [sample()], stream=output, input_stream=io.StringIO(), splash=True)
            splash.assert_not_called()
        self.assertEqual(result, "plain")
        self.assertIn("KNOT", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())

    def test_q_restores_terminal_and_does_not_signal_workflow_stop(self):
        stop = threading.Event()
        terminal = FakeTerminal(["quit"])
        with patch("runtime.monitor._Terminal", return_value=terminal):
            result = watch(lambda: [sample()], stop_event=stop, embedded=True)
        self.assertEqual(result, "closed")
        self.assertFalse(stop.is_set())
        self.assertTrue(terminal.exited)

    def test_keyboard_selects_tasks_then_projects(self):
        terminal = FakeTerminal(["down", "next", "quit"])
        runs = [sample(), sample("two", "Second project")]
        with patch("runtime.monitor._Terminal", return_value=terminal):
            watch(lambda: runs)
        self.assertIn("SELECTED: Build frontend", terminal.frames[0])
        self.assertIn("SELECTED: Build backend", terminal.frames[1])
        self.assertIn("Second project  |  codex", terminal.frames[2])

    def test_selection_survives_registry_order_changes(self):
        terminal = FakeTerminal(["next", None, "quit"])
        first, second = sample(), sample("two", "Second project")
        calls = 0
        def read():
            nonlocal calls
            calls += 1
            return [first, second] if calls == 1 else [second, first]
        with patch("runtime.monitor._Terminal", return_value=terminal):
            watch(read)
        self.assertIn("Second project  |  codex", terminal.frames[1])

    def test_final_snapshot_is_read_after_stop_event(self):
        stop = threading.Event()
        terminal = FakeTerminal([None, "quit"])
        runs = [sample()]
        calls = 0
        def read():
            nonlocal calls
            calls += 1
            result = copy.deepcopy(runs)
            if calls >= 2:
                result[0]["status"] = "completed"
            return result
        def on_draw():
            if len(terminal.frames) == 1:
                stop.set()
        terminal.on_draw = on_draw
        output = io.StringIO()
        with patch("runtime.monitor._Terminal", return_value=terminal):
            result = watch(read, stop_event=stop, stream=output)
        self.assertEqual(result, "finished")
        self.assertEqual(calls, 2)
        self.assertIn("0 running", terminal.frames[-1])
        self.assertTrue(terminal.exited)
        self.assertIn("WORKFLOW UPDATE", output.getvalue())
        self.assertIn("DONE", output.getvalue())
        self.assertLessEqual(len(output.getvalue().splitlines()), 5)
        self.assertNotIn("\x1b", output.getvalue())

    def test_splash_can_be_skipped_and_q_remains_read_only(self):
        terminal = FakeTerminal(["skip", "quit"])
        stop = threading.Event()
        with patch("runtime.monitor._Terminal", return_value=terminal):
            result = watch(lambda: [sample()], stop_event=stop, splash=True)
        self.assertEqual(result, "closed")
        self.assertFalse(stop.is_set())
        self.assertIn("Your agents. One workflow.", terminal.frames[0])
        self.assertIn("LOCAL AGENTS", terminal.frames[1])

    def test_q_or_ctrl_c_during_splash_restores_terminal(self):
        for key in ("quit", "interrupt"):
            with self.subTest(key=key):
                terminal = FakeTerminal([key])
                with patch("runtime.monitor._Terminal", return_value=terminal):
                    if key == "interrupt":
                        with self.assertRaises(KeyboardInterrupt):
                            watch(lambda: [sample()], splash=True, embedded=True)
                    else:
                        self.assertEqual(watch(lambda: [sample()], splash=True), "closed")
                self.assertTrue(terminal.exited)

    def test_stop_during_splash_goes_straight_to_final_fixed_mark(self):
        stop = threading.Event()
        terminal = FakeTerminal([None], on_draw=stop.set)
        run = sample()
        run.update(status="completed", live=False)
        output = io.StringIO()
        with patch("runtime.monitor._Terminal", return_value=terminal):
            result = watch(lambda: [run], stop_event=stop, splash=True, stream=output)
        self.assertEqual(result, "finished")
        self.assertEqual(len(terminal.frames), 2)
        self.assertIn("DONE", output.getvalue())
        self.assertTrue(terminal.exited)

    def test_reduced_motion_skips_the_splash(self):
        terminal = FakeTerminal(["quit"])
        with patch("runtime.monitor._Terminal", return_value=terminal), \
             patch.dict("runtime.monitor.os.environ", {"KNOT_NO_ANIMATION": "1"}), \
             patch("runtime.monitor._show_splash") as splash:
            watch(lambda: [sample()], splash=True)
        splash.assert_not_called()

    def test_ctrl_c_interrupts_embedded_runner_but_q_only_closes(self):
        terminal = FakeTerminal(["interrupt"])
        with patch("runtime.monitor._Terminal", return_value=terminal), self.assertRaises(KeyboardInterrupt):
            watch(lambda: [sample()], embedded=True)
        self.assertTrue(terminal.exited)

    def test_buffered_posix_keys_are_consumed_without_more_input(self):
        class Input:
            def fileno(self):
                return 123
        terminal = _Terminal(io.StringIO(), Input())
        terminal.enabled = True
        with patch("runtime.monitor.os.name", "posix"), \
             patch("select.select", side_effect=[([123], [], []), ([], [], [])]), \
             patch("runtime.monitor.os.read", return_value=b"jq") as read:
            self.assertEqual(terminal.key(), "down")
            self.assertEqual(terminal.key(), "quit")
            read.assert_called_once()

    def test_redraw_erases_shortened_rows(self):
        output = io.StringIO()
        terminal = _Terminal(output, io.StringIO())
        terminal.enabled = True
        terminal.draw("short\nsecond")
        self.assertIn("short\x1b[K\n", output.getvalue())
        self.assertTrue(output.getvalue().endswith("second\x1b[K\x1b[J"))

    def test_terminal_restoration_happens_on_unexpected_reader_exception(self):
        terminal = FakeTerminal()
        def explode():
            raise RuntimeError("unexpected read failure")
        with patch("runtime.monitor._Terminal", return_value=terminal), self.assertRaises(RuntimeError):
            watch(explode)
        self.assertTrue(terminal.exited)

    def test_real_terminal_exit_restores_cursor_and_alternate_screen(self):
        output = io.StringIO()
        terminal = _Terminal(output, io.StringIO())
        terminal.enabled = True
        terminal.__exit__(None, None, None)
        self.assertIn("\x1b[?25h", output.getvalue())
        self.assertIn("\x1b[?1049l", output.getvalue())
        self.assertIn("\x1b[0m", output.getvalue())
        self.assertFalse(terminal.enabled)

    def test_shortcuts_are_read_only_navigation(self):
        self.assertEqual(_key_name("q"), "quit")
        self.assertEqual(_key_name("\x03"), "interrupt")
        self.assertEqual(_key_name("\t"), "next")
        self.assertEqual(_key_name("j"), "down")
        self.assertEqual(_key_name("a"), "skip")  # Skips splash, never approves.


if __name__ == "__main__":
    unittest.main()
