"""Plain terminal artwork derived from KNOT's tied and open workflow marks.

The caller owns color, cursor movement and animation timing. These functions do
not print, sleep, launch work, or include terminal escape sequences.
"""
from __future__ import annotations

import math


MARK_WIDTH = 11
MARK_HEIGHT = 5
FRAME_SECONDS = 0.8
TAGLINE = "Your agents. One workflow."
STARTING_TEXT = "Starting local workspace..."

# The tied mark keeps the original's leaning spine, loop at the upper right,
# crossing ribbon, and lower-right leg. The open mark is one input branching
# into two outputs, with a port in each node (public/brand/KNOT-mark*.svg).
_MARKS = {
    "k": (
        "  ██  ▄██▄ ",
        "  ██▄█▀ ▀█ ",
        " ▄██▀▄▄█▀  ",
        "▄██▄██▄    ",
        "██▀  ▀██▄  ",
    ),
    "workflow": (
        "       [○] ",
        "     ╭──╯  ",
        "[○]──┤     ",
        "     ╰──╮  ",
        "       [○] ",
    ),
}
_ASCII_MARKS = {
    "k": (
        "  ##  +##+ ",
        "  ##+#- -# ",
        " +##-++#-  ",
        "+##+##+    ",
        "##-  -##+  ",
    ),
    "workflow": (
        "       [+] ",
        "     +--+  ",
        "[+]--+     ",
        "     +--+  ",
        "       [+] ",
    ),
}

_LETTERS = (
    ("██  ██", "██ ██ ", "████  ", "██ ██ ", "██  ██"),
    ("██   ██", "███  ██", "██ █ ██", "██  ███", "██   ██"),
    (" ████ ", "██  ██", "██  ██", "██  ██", " ████ "),
    ("██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "),
)
_WORDMARK = tuple("  ".join(letter[row] for letter in _LETTERS) for row in range(MARK_HEIGHT))


def logo_lines(form: str = "k", ascii_only: bool = False) -> tuple[str, ...]:
    """Return a fixed 11-cell by 5-row mark, without color or escape codes."""
    if form not in _MARKS:
        raise ValueError("KNOT mark form must be 'k' or 'workflow'")
    marks = _ASCII_MARKS if ascii_only else _MARKS
    return tuple(line.ljust(MARK_WIDTH) for line in marks[form])


def frame_form(active: bool, elapsed: float) -> str:
    """Alternate tied/open frames while work is active; always rest on K."""
    if not active:
        return "k"
    try:
        seconds = float(elapsed)
    except (TypeError, ValueError, OverflowError):
        return "k"
    if not math.isfinite(seconds) or seconds < 0:
        return "k"
    return "workflow" if int(seconds / FRAME_SECONDS) % 2 else "k"


def splash_lines(width: int = 100, height: int = 32, ascii_only: bool = False) -> str:
    """Center startup artwork within a terminal, simplifying on small screens.

    All glyphs occupy one terminal cell in the supported monospace layouts.
    ASCII output is suitable for terminals without block/box-drawing support.
    Captions are omitted when they cannot fit; the brand remains visible.
    """
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return ""
    # Avoid accidental huge allocations from a malformed terminal size.
    width, height = min(width, 1000), min(height, 300)
    mark = logo_lines(ascii_only=ascii_only)
    wordmark = tuple(line.replace("█", "#") for line in _WORDMARK) if ascii_only else _WORDMARK
    combined = tuple(mark[row] + "    " + wordmark[row] for row in range(MARK_HEIGHT))
    if width >= len(combined[0]) and height >= MARK_HEIGHT:
        artwork = list(combined)
    elif width >= len(wordmark[0]) and height >= MARK_HEIGHT:
        artwork = list(wordmark)
    elif width >= MARK_WIDTH and height >= MARK_HEIGHT + 2:
        artwork = [*mark, "", "KNOT"]
    else:
        artwork = ["KNOT"[:width]]

    content = list(artwork)
    if width >= len(TAGLINE) and height >= len(content) + 2:
        content.extend(["", TAGLINE])
    if width >= len(STARTING_TEXT) and height >= len(content) + 2:
        content.extend(["", STARTING_TEXT])
    top = max(0, (height - len(content)) // 2)
    lines = [""] * top
    for line in content:
        # Leave the right margin empty instead of padding to the final column:
        # printing trailing spaces there can trigger terminal auto-wrapping.
        lines.append((" " * max(0, (width - len(line)) // 2) + line).rstrip())
    return "\n".join(lines)
