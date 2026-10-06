"""Absolute mouse events must carry MOUSEEVENTF_MOVE (#441).

Win32 only reads a mouse_event's dx/dy when MOUSEEVENTF_MOVE is set. Without
it the button event is delivered wherever the cursor already happens to be and
the coordinates every click helper computes are dead weight, so a click only
lands on target while the preceding SetCursorPos happens to succeed.
"""

import pytest

from windows_mcp.uia import core
from windows_mcp.uia.enums import MouseEventFlag

# A single 3840x2160 monitor.
SINGLE_MONITOR = (0, 0, 3840, 2160)
# A second monitor placed left of and above the primary one, so points on it
# carry legitimately negative coordinates.
SPANNING_MONITORS = (-1920, -200, 5760, 2360)

POSITIONING_FLAGS = MouseEventFlag.Move | MouseEventFlag.Absolute | MouseEventFlag.VirtualDesk


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int, int]]:
    """Record every mouse_event instead of injecting real input."""
    recorded: list[tuple[int, int, int]] = []
    monkeypatch.setattr(
        core,
        "mouse_event",
        lambda flags, dx, dy, data, extra: recorded.append((flags, dx, dy)),
    )
    monkeypatch.setattr(core, "SetCursorPos", lambda x, y: True)
    monkeypatch.setattr(core, "GetVirtualScreenRect", lambda: SINGLE_MONITOR)
    return recorded


def _to_pixels(rect: tuple[int, int, int, int], nx: int, ny: int) -> tuple[int, int]:
    """Map a normalized absolute coordinate back to the pixel Windows resolves."""
    left, top, width, height = rect
    return (
        left + round(nx * (width - 1) / 65535),
        top + round(ny * (height - 1) / 65535),
    )


def test_click_sets_move_alongside_absolute(events: list[tuple[int, int, int]]) -> None:
    core.Click(2000, 2124, waitTime=0)

    assert len(events) == 2
    for flags, _, _ in events:
        assert flags & MouseEventFlag.Move, "dx/dy are ignored without MOUSEEVENTF_MOVE"
        assert flags & MouseEventFlag.Absolute
        assert flags & MouseEventFlag.VirtualDesk
    assert events[0][0] & MouseEventFlag.LeftDown
    assert events[1][0] & MouseEventFlag.LeftUp


@pytest.mark.parametrize(
    ("point"),
    [
        (0, 0),
        (1, 1),
        (960, 540),
        (2000, 2124),
        (3839, 2159),
    ],
)
def test_absolute_coordinates_resolve_to_the_requested_pixel(
    events: list[tuple[int, int, int]],
    point: tuple[int, int],
) -> None:
    core.Click(*point, waitTime=0)

    for _, nx, ny in events:
        assert 0 <= nx <= 65535
        assert 0 <= ny <= 65535
        assert _to_pixels(SINGLE_MONITOR, nx, ny) == point


def test_point_on_a_monitor_left_of_primary_is_not_mapped_onto_the_primary(
    events: list[tuple[int, int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VIRTUALDESK normalization is what keeps multi-monitor clicks correct.

    Normalizing against the primary monitor instead would make every point
    outside it unreachable -- a negative x cannot be expressed at all.
    """
    monkeypatch.setattr(core, "GetVirtualScreenRect", lambda: SPANNING_MONITORS)

    core.Click(-1500, -100, waitTime=0)

    for _, nx, ny in events:
        assert 0 <= nx <= 65535
        assert 0 <= ny <= 65535
        assert _to_pixels(SPANNING_MONITORS, nx, ny) == (-1500, -100)


@pytest.mark.parametrize(
    ("helper", "expected_flags"),
    [
        ("Click", [MouseEventFlag.LeftDown, MouseEventFlag.LeftUp]),
        ("RightClick", [MouseEventFlag.RightDown, MouseEventFlag.RightUp]),
        ("MiddleClick", [MouseEventFlag.MiddleDown, MouseEventFlag.MiddleUp]),
        ("PressMouse", [MouseEventFlag.LeftDown]),
        ("RightPressMouse", [MouseEventFlag.RightDown]),
        ("MiddlePressMouse", [MouseEventFlag.MiddleDown]),
    ],
)
def test_every_positioned_helper_moves_to_its_target(
    events: list[tuple[int, int, int]],
    helper: str,
    expected_flags: list[MouseEventFlag],
) -> None:
    getattr(core, helper)(640, 480, waitTime=0)

    assert len(events) == len(expected_flags)
    for (flags, nx, ny), button in zip(events, expected_flags, strict=True):
        assert flags & button
        assert flags & POSITIONING_FLAGS == POSITIONING_FLAGS
        assert _to_pixels(SINGLE_MONITOR, nx, ny) == (640, 480)


@pytest.mark.parametrize(
    ("helper", "expected_flag"),
    [
        ("ReleaseMouse", MouseEventFlag.LeftUp),
        ("RightReleaseMouse", MouseEventFlag.RightUp),
        ("MiddleReleaseMouse", MouseEventFlag.MiddleUp),
    ],
)
def test_release_helpers_release_at_the_current_cursor_position(
    events: list[tuple[int, int, int]],
    monkeypatch: pytest.MonkeyPatch,
    helper: str,
    expected_flag: MouseEventFlag,
) -> None:
    monkeypatch.setattr(core, "GetCursorPos", lambda: (1234, 567))

    getattr(core, helper)(waitTime=0)

    assert len(events) == 1
    flags, nx, ny = events[0]
    assert flags & expected_flag
    assert flags & POSITIONING_FLAGS == POSITIONING_FLAGS
    assert _to_pixels(SINGLE_MONITOR, nx, ny) == (1234, 567)


def test_single_pixel_desktop_does_not_divide_by_zero(
    events: list[tuple[int, int, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "GetVirtualScreenRect", lambda: (0, 0, 1, 1))

    core.Click(0, 0, waitTime=0)

    assert events == [
        (MouseEventFlag.LeftDown | POSITIONING_FLAGS, 0, 0),
        (MouseEventFlag.LeftUp | POSITIONING_FLAGS, 0, 0),
    ]
