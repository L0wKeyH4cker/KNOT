"""Read-only, dependency-free terminal dashboard for local KNOT runs."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import shutil
import sys
import time
import unicodedata
from typing import Callable, TextIO

from .activity import sanitize_text
from .terminal_brand import frame_form, logo_lines, splash_lines

STATUS = {
    "pending": "WAITING", "running": "RUNNING", "succeeded": "DONE",
    "completed": "DONE", "failed": "FAILED", "blocked": "BLOCKED",
    "skipped": "SKIPPED", "waiting_review": "REVIEW", "disconnected": "OFFLINE",
    "interrupted": "STOPPED", "cancelled": "STOPPED", "stopped": "STOPPED",
}


def cell_width(text: str) -> int:
    """Conservative terminal width, including Chinese and combining characters."""
    return sum(0 if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf")
               else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def clip(text, width: int, marker: str = "...") -> str:
    clean = sanitize_text(str(text), limit=4000)
    return _crop(clean, width, marker)


def _crop(clean: str, width: int, marker: str = "...") -> str:
    """Crop already-sanitized layout without collapsing alignment spaces."""
    width = max(0, width)
    if cell_width(clean) <= width:
        return clean
    suffix = marker if width >= len(marker) else ""
    budget = width - cell_width(suffix)
    result, used = [], 0
    for char in clean:
        size = cell_width(char)
        if used + size > budget:
            break
        result.append(char)
        used += size
    return "".join(result) + suffix


def _pad(value, width: int) -> str:
    text = clip(value, width)
    return text + " " * max(0, width - cell_width(text))


def _timestamp(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (ValueError, OverflowError):
            pass
    return None


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _elapsed(item: dict, now: float, end=None) -> str:
    start = _timestamp(item.get("started_at"))
    finish = _timestamp(item.get("finished_at")) or _timestamp(end) or now
    return _duration(finish - start) if start is not None else "--"


def _project(run: dict) -> str:
    project = run.get("project", {})
    if isinstance(project, dict):
        return sanitize_text(project.get("name") or "Untitled project", limit=500)
    return sanitize_text(project or run.get("name") or "Untitled project", limit=500)


def _run_status(run: dict) -> str:
    status = sanitize_text(run.get("display_status") or run.get("status") or "pending")
    if status == "running" and run.get("live") is False:
        return "disconnected"
    return status


def _tasks(run: dict) -> list[tuple[str, dict]]:
    nodes = run.get("nodes", {})
    if not isinstance(nodes, dict):
        return []
    return [(str(nid), node) for nid, node in nodes.items()
            if isinstance(node, dict) and node.get("type") == "agent_task"]


def _window(items: list, selected: int, count: int) -> tuple[int, list]:
    start = max(0, min(selected - count // 2, len(items) - count))
    return start, items[start:start + count]


def _activity(node: dict) -> str:
    activity = node.get("activity") or {}
    if isinstance(activity, dict):
        return sanitize_text(activity.get("text") or activity.get("kind") or "", limit=1000)
    return sanitize_text(activity, limit=1000)


def _event_text(event: dict, nodes: dict) -> str:
    node = nodes.get(event.get("node_id"), {})
    label = event.get("label") or (node.get("label") if isinstance(node, dict) else None) or event.get("node_id") or "Workflow"
    detail = event.get("activity") or event.get("detail") or {}
    if isinstance(detail, dict) and isinstance(detail.get("activity"), dict):
        detail = detail["activity"]
    body = event.get("text") or event.get("error")
    if not body and isinstance(detail, dict):
        body = detail.get("text") or detail.get("kind") or detail.get("event")
    if not body:
        body = str(event.get("event", "Update")).replace("_", " ")
    when = _timestamp(event.get("time"))
    try:
        stamp = datetime.fromtimestamp(when).strftime("%H:%M:%S") if when is not None else "--:--:--"
    except (ValueError, OverflowError, OSError):
        stamp = "--:--:--"
    return sanitize_text(f"{stamp}  {label}: {body}", limit=1000)


def _fit(lines: list[str], footer: str, width: int, height: int) -> str:
    content = lines[:max(0, height - 1)]
    if height > 0:
        content.append(footer)
    return "\n".join(_crop(line, width) for line in content)


def _brand_header(left: list[str], width: int, form: str, ascii_only: bool) -> list[str]:
    mark = logo_lines(form, ascii_only=ascii_only)
    mark_width = max(cell_width(row) for row in mark)
    text_width = max(0, width - mark_width - 3)
    result = []
    for index, art in enumerate(mark):
        text = _crop(left[index] if index < len(left) else "", text_width)
        result.append(text + " " * (width - mark_width - cell_width(text)) + art)
    return result


def _live_count(runs: list[dict]) -> int:
    return sum(_run_status(run) == "running" and run.get("live") is True for run in runs)


def render_dashboard(runs: list[dict], selected_run: int = 0, selected_task: int = 0,
                     width: int = 100, height: int = 32, now: float | None = None,
                     animation_elapsed: float = 0, ascii_only: bool = False) -> str:
    """Render safe plain text. Only a live runner animates; counts are actual tasks."""
    width, height = max(1, min(int(width), 240)), max(1, min(int(height), 100))
    now = time.time() if now is None else now
    runs = [run for run in runs if isinstance(run, dict)]
    footer = "Up/Down: task  |  n/p or Tab: project  |  q: close monitor (jobs keep running)"
    if width < 68:
        footer = "q close | j/k task | n/p project"
    active = _live_count(runs)
    form = frame_form(active > 0 and os.environ.get("KNOT_NO_ANIMATION") != "1", animation_elapsed)
    full_header = width >= 54 and height >= 20
    title = "KNOT / LOCAL AGENTS"
    header = title if width >= 32 else "KNOT / AGENTS"
    if not runs:
        empty = [title, "No local workflows found.", "", "Your agents will appear here.", ""]
        lines = _brand_header(empty, width, "k", ascii_only) if full_header else [header, empty[1]]
        lines.extend(["", "Start a downloaded workspace to see its agents here.",
                      "Older runs: use python knot.py monitor --root PATH"])
        return _fit(lines, footer, width, height)
    selected_run = max(0, min(selected_run, len(runs) - 1))
    run = runs[selected_run]
    tasks = _tasks(run)
    selected_task = max(0, min(selected_task, len(tasks) - 1))
    done = sum(task.get("status") == "succeeded" for _, task in tasks)
    skipped = sum(task.get("status") == "skipped" for _, task in tasks)
    review = sum(_run_status(item) == "waiting_review" for item in runs)
    run_status = _run_status(run)
    execution = run.get("execution") if isinstance(run.get("execution"), dict) else {}
    backend = sanitize_text(execution.get("backend") or run.get("mode") or "unknown")
    model = sanitize_text(execution.get("model") or "assistant default")
    end = run.get("updated_at") if run_status not in ("running", "pending") else None
    task_count = f"{done}/{len(tasks)} agent tasks done" + (f" | {skipped} skipped" if skipped else "")
    project_word = "project" if len(runs) == 1 else "projects"
    overview = f"{len(runs)} {project_word}  |  {active} running  |  {review} waiting for review"
    project_line = f"{_project(run)}  |  {backend} / {model}"
    counts_line = f"{task_count}  |  elapsed {_elapsed(run, now, end)}"
    if not full_header:
        # Keep task details readable when a five-row mark cannot fit.
        small_mark = "K" if form == "k" else "o>o"
        lines = [_pad(header, max(0, width - 4)) + small_mark, overview,
                 f"[{selected_run + 1}/{len(runs)}] {_project(run)}",
                      f"{STATUS.get(run_status, run_status.upper())} | {backend} | {_elapsed(run, now, end)}",
                      task_count]
        if tasks:
            nid, node = tasks[selected_task]
            status = "disconnected" if run_status == "disconnected" and node.get("status") == "running" else sanitize_text(node.get("status", "pending"))
            lines.extend([f"> {selected_task + 1}. {sanitize_text(node.get('label') or nid)}",
                          f"{STATUS.get(status, status.upper())} | {sanitize_text(node.get('agent_name') or 'Agent')}",
                          _activity(node) or sanitize_text(node.get("error") or "No task activity received yet.")])
        if run_status == "disconnected":
            lines.append("Runner heartbeat missing; last saved state shown.")
        elif run_status == "waiting_review":
            lines.append("Review in the runner terminal; this monitor is read-only.")
        return _fit(lines, footer, width, height)

    lines = _brand_header([title, overview, "", project_line, counts_line], width, form, ascii_only)
    if run.get("root"):
        lines.append(sanitize_text(run["root"], limit=1000))
    lines.append("")
    project_slots = min(3 if height >= 30 else 2, len(runs))
    start, projects = _window(runs, selected_run, project_slots)
    lines.append("PROJECTS")
    for index, item in enumerate(projects, start):
        state = _run_status(item)
        label = STATUS.get(state, state.upper())
        marker = ">" if index == selected_run else " "
        lines.append(f"{marker} {_pad(_project(item), width - 16)} {label}")
    if run_status == "disconnected":
        lines.append("OFFLINE: no fresh runner heartbeat. Running tasks below show their last saved state.")
    elif run_status == "waiting_review":
        lines.append("REVIEW NEEDED: approve or reject in the runner terminal. This monitor is read-only.")
    lines.extend(["", "AGENT TASKS"])
    task_slots = min(max(1, height - len(lines) - 7), 7, len(tasks))
    if not tasks:
        lines.append("  No agent-task metadata in this run. See the recent workflow events below.")
    else:
        offset, visible = _window(tasks, selected_task, task_slots)
        for index, (nid, node) in enumerate(visible, offset):
            state = sanitize_text(node.get("status", "pending"))
            if state == "running" and run_status == "disconnected":
                state = "disconnected"
            marker = ">" if index == selected_task else " "
            name = str(node.get("label") or nid)
            if node.get("agent_name"):
                name += " / " + str(node["agent_name"])
            frozen = (run.get("heartbeat_at") or run.get("updated_at")) if state == "disconnected" else None
            lines.append(f"{marker}  {_pad(STATUS.get(state, state.upper()), 10)} {_pad(name, width - 26)} {_elapsed(node, now, frozen)}")
    if tasks:
        nid, node = tasks[selected_task]
        activity = _activity(node)
        last = _timestamp(node.get("last_activity_at"))
        age = f" | last activity {_duration(now - last)} ago" if last is not None else ""
        lines.extend(["", f"SELECTED: {sanitize_text(node.get('label') or nid)}{age}"])
        if node.get("error"):
            lines.append("Error: " + sanitize_text(node["error"], limit=1000))
        lines.append(activity or "No task activity received yet. Waiting for the next CLI event.")
    nodes = run.get("nodes") if isinstance(run.get("nodes"), dict) else {}
    events = run.get("last_events") or run.get("events") or []
    events = [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []
    remaining = height - len(lines) - 2
    if remaining > 0:
        lines.append("RECENT ACTIVITY")
        lines.extend(_event_text(event, nodes) for event in events[-min(remaining, 6):])
        if not events:
            lines.append("No activity recorded yet.")
    return _fit(lines, footer, width, height)


def colorize_frame(frame: str, enabled: bool = True) -> str:
    """Style an already-sanitized renderer result; art and snapshots stay plain."""
    if not enabled or "NO_COLOR" in os.environ:
        return frame
    base = "\x1b[40m\x1b[38;2;191;219;254m"
    accent = "\x1b[1m\x1b[38;2;147;197;253m"
    muted = "\x1b[38;2;148;163;184m"
    selected = "\x1b[48;2;15;23;42m\x1b[38;2;224;242;254m"
    result = []
    for line in frame.splitlines():
        style = ""
        if line.startswith("> "):
            style = selected
        elif line.startswith(("KNOT", "PROJECTS", "AGENT TASKS", "SELECTED:", "RECENT ACTIVITY", "REVIEW NEEDED", "OFFLINE:", "Error:")):
            style = accent
        elif line.startswith(("Up/Down:", "q close", "Read error:")) or " projects  | " in line or " project  | " in line:
            style = muted
        result.append(base + style + line + "\x1b[0m")
    return "\n".join(result)


def _ascii_output(stream: TextIO) -> bool:
    try:
        artwork = "".join(logo_lines("k") + logo_lines("workflow")) + splash_lines(100, 32)
        artwork.encode(getattr(stream, "encoding", None) or "utf-8")
        return False
    except (UnicodeEncodeError, LookupError):
        return True


def _finished_snapshot(runs: list[dict], selected_run: int, width: int, ascii_only: bool) -> str:
    """Leave a small fixed K in scrollback after the alternate screen closes."""
    left = ["KNOT / WORKFLOW UPDATE", "No workflow snapshot available.", "", "", ""]
    if runs:
        run = runs[max(0, min(selected_run, len(runs) - 1))]
        tasks = _tasks(run)
        status = _run_status(run)
        left[1] = _project(run)
        left[2] = STATUS.get(status, status.upper())
        left[3] = f"{sum(task.get('status') == 'succeeded' for _, task in tasks)}/{len(tasks)} agent tasks done"
        if status == "waiting_review":
            left[4] = "Review required. Continue in the runner terminal."
        elif status == "disconnected":
            left[4] = "Runner offline; last saved state shown."
    if width < 40:
        return "\n".join(_crop(line, width) for line in ["K / KNOT", *left[1:]] if line)
    return "\n".join(_brand_header(left, width, "k", ascii_only))


class _Terminal:
    """Own terminal state only while watching; always restore it on exit."""
    def __init__(self, stream: TextIO, input_stream: TextIO):
        self.stream, self.input = stream, input_stream
        self.enabled = False
        self._windows = None
        self._termios = None
        self._buffer = ""

    def _write(self, text: str) -> None:
        encoding = getattr(self.stream, "encoding", None)
        if encoding:
            text = text.encode(encoding, "replace").decode(encoding, "replace")
        self.stream.write(text)
        self.stream.flush()

    def __enter__(self):
        try:
            interactive = self.stream.isatty() and self.input.isatty()
        except (AttributeError, OSError):
            interactive = False
        if not interactive or os.environ.get("TERM") == "dumb":
            return self
        try:
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                kernel.GetConsoleMode.restype = wintypes.BOOL
                kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.SetConsoleMode.restype = wintypes.BOOL
                handle = msvcrt.get_osfhandle(self.stream.fileno())
                mode = wintypes.DWORD()
                if not kernel.GetConsoleMode(handle, ctypes.byref(mode)) or not kernel.SetConsoleMode(handle, mode.value | 0x0004):
                    return self
                self._windows = (kernel, handle, mode.value)
            else:
                import termios
                import tty
                fd = self.input.fileno()
                previous = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                self._termios = (fd, previous)
            self.enabled = True
            self._write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
            return self
        except (OSError, ValueError, AttributeError):
            self.__exit__(None, None, None)
            return self

    def __exit__(self, *_):
        try:
            if self.enabled:
                self._write("\x1b[0m\x1b[?25h\x1b[?1049l")
        finally:
            if self._termios:
                import termios
                fd, previous = self._termios
                termios.tcsetattr(fd, termios.TCSADRAIN, previous)
                self._termios = None
            if self._windows:
                kernel, handle, mode = self._windows
                kernel.SetConsoleMode(handle, mode)
                self._windows = None
            self.enabled = False

    def size(self) -> tuple[int, int]:
        try:
            size = os.get_terminal_size(self.stream.fileno())
        except (OSError, ValueError, AttributeError):
            size = shutil.get_terminal_size((100, 32))
        return size.columns, size.lines

    def draw(self, frame: str) -> None:
        # Clear each row so a shorter replacement cannot leave old text behind.
        self._write("\x1b[H" + "\x1b[K\n".join(frame.splitlines()) + "\x1b[K\x1b[J"
                    if self.enabled else frame + "\n")

    def key(self) -> str | None:
        if not self.enabled:
            return None
        if os.name == "nt":
            import msvcrt
            if not msvcrt.kbhit():
                return None
            value = msvcrt.getwch()
            if value in ("\x00", "\xe0"):
                return {"H": "up", "P": "down", "K": "previous", "M": "next"}.get(msvcrt.getwch())
            return _key_name(value)
        import select
        fd = self.input.fileno()
        if select.select([fd], [], [], 0)[0]:
            self._buffer += os.read(fd, 64).decode("utf-8", "ignore")
        for sequence, name in (("\x1b[A", "up"), ("\x1b[B", "down"), ("\x1b[C", "next"), ("\x1b[D", "previous")):
            if self._buffer.startswith(sequence):
                self._buffer = self._buffer[len(sequence):]
                return name
        if self._buffer.startswith("\x1b") and len(self._buffer) < 3:
            return None
        if not self._buffer:
            return None
        value, self._buffer = self._buffer[0], self._buffer[1:]
        return _key_name(value)


def _key_name(value: str) -> str | None:
    return {"q": "quit", "Q": "quit", "\x03": "interrupt", "j": "down", "k": "up",
            "n": "next", "p": "previous", "\t": "next"}.get(value, "skip" if value else None)


def _show_splash(terminal, stop_event, embedded: bool, ascii_only: bool) -> str:
    """A short, skippable introduction; the execution worker is already running."""
    deadline = time.monotonic() + 0.8
    previous_size = None
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return "finished"
        size = terminal.size()
        if size != previous_size:
            width, height = size
            terminal.draw(colorize_frame(splash_lines(max(1, width - 1), height, ascii_only=ascii_only)))
            previous_size = size
        key = terminal.key()
        if key == "quit":
            return "closed"
        if key == "interrupt":
            if embedded:
                raise KeyboardInterrupt
            return "closed"
        if key is not None:
            return "skipped"
        delay = min(0.05, max(0, deadline - time.monotonic()))
        if stop_event is not None:
            stop_event.wait(delay)
        else:
            time.sleep(delay)
    return "shown"


def watch(read_runs: Callable[[], list[dict]], stop_event=None, embedded: bool = False,
          stream: TextIO | None = None, input_stream: TextIO | None = None,
          interval: float = 0.25, splash: bool = True) -> str:
    """Observe snapshots; q closes this view and never cancels a workflow."""
    stream = stream or sys.stdout
    input_stream = input_stream or sys.stdin
    selected_run, selected_task = 0, 0
    selected_id = None
    interval = max(0.05, min(float(interval), 5.0))
    ascii_only = _ascii_output(stream)
    reduced_motion = os.environ.get("KNOT_NO_ANIMATION") == "1"
    with _Terminal(stream, input_stream) as terminal:
        if terminal.enabled and splash and not reduced_motion:
            if _show_splash(terminal, stop_event, embedded, ascii_only) == "closed":
                return "closed"
        animation_started = time.monotonic()
        while True:
            finishing = stop_event is not None and stop_event.is_set()
            try:
                runs = read_runs()
                runs = [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
            except (OSError, ValueError) as error:
                runs = []
                error_text = sanitize_text(str(error), limit=250)
            else:
                error_text = ""
            if selected_id is not None:
                selected_run = next((i for i, run in enumerate(runs) if run.get("run_id") == selected_id), selected_run)
            selected_run = max(0, min(selected_run, len(runs) - 1))
            if runs:
                selected_id = runs[selected_run].get("run_id")
                selected_task = max(0, min(selected_task, len(_tasks(runs[selected_run])) - 1))
            width, height = terminal.size()
            # Leave the final column free to avoid automatic wrapping/scrolling.
            width = max(1, width - 1) if terminal.enabled else width
            elapsed = 0 if finishing or reduced_motion or not terminal.enabled else time.monotonic() - animation_started
            frame = render_dashboard(runs, selected_run, selected_task, width, height,
                                     animation_elapsed=elapsed, ascii_only=ascii_only)
            if error_text:
                frame = _fit(frame.splitlines()[:-1], "Read error: " + error_text, width, height)
            terminal.draw(colorize_frame(frame, enabled=terminal.enabled))
            if not terminal.enabled:
                return "plain"
            if stop_event is not None and stop_event.is_set():
                if finishing:
                    break
                # Completion could have arrived while reading or drawing.
                continue
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                key = terminal.key()
                if key == "quit":
                    return "closed"
                if key == "interrupt":
                    if embedded:
                        raise KeyboardInterrupt
                    return "closed"
                if key in ("next", "previous") and runs:
                    selected_run = (selected_run + (1 if key == "next" else -1)) % len(runs)
                    selected_id = runs[selected_run].get("run_id")
                    selected_task = 0
                    break
                if key in ("up", "down") and runs:
                    tasks = _tasks(runs[selected_run])
                    if tasks:
                        selected_task = (selected_task + (1 if key == "down" else -1)) % len(tasks)
                    break
                if stop_event is not None and stop_event.wait(0.05):
                    break
                if stop_event is None:
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    # The alternate screen is restored before writing this small, fixed mark.
    final = _finished_snapshot(runs, selected_run, width, ascii_only)
    # Windows may have restored a console mode without ANSI support by now.
    # Keep this scrollback summary plain and preserve the user's original colors.
    encoding = getattr(stream, "encoding", None)
    if encoding:
        final = final.encode(encoding, "replace").decode(encoding, "replace")
    stream.write(final + "\n")
    stream.flush()
    return "finished"
