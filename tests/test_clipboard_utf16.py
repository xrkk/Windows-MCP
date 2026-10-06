"""SetClipboardText must size its buffer in UTF-16 units, not code points (#437).

A character outside the BMP occupies two UTF-16 units, so sizing from
len(text) under-allocates by one unit per surrogate pair. wcsncpy then stops
short of the tail and, because the source is longer than the copy count, never
writes the terminating NUL -- leaving an unterminated CF_UNICODETEXT behind.

The Win32 clipboard entry points are replaced with a stand-in heap block so the
real wcsncpy copy still runs and the resulting buffer can be read back.
"""

import ctypes

import pytest

from windows_mcp.uia import core

EARTH = "\U0001f30d"
GRINNING = "\U0001f600"


class FakeGlobalHeap:
    """Stands in for the moveable global block the clipboard takes ownership of."""

    HANDLE = 0xABCD

    def __init__(self) -> None:
        self.allocated_bytes: int | None = None
        self.copy_count: int | None = None
        self.stored_format: int | None = None
        self._buffer: ctypes.Array[ctypes.c_char] | None = None

    def alloc(self, flags: int, size: int) -> int:
        self.allocated_bytes = size
        # Deliberately not zero-filled: a buffer the copy fails to terminate
        # must not read back as terminated by accident.
        self._buffer = ctypes.create_string_buffer(b"\xff" * size, size)
        return self.HANDLE

    def lock(self, handle: object) -> int:
        return ctypes.addressof(self._buffer)

    def read_text(self) -> str:
        return ctypes.wstring_at(ctypes.addressof(self._buffer))

    @property
    def raw(self) -> bytes:
        return self._buffer.raw


@pytest.fixture
def heap(monkeypatch: pytest.MonkeyPatch) -> FakeGlobalHeap:
    fake = FakeGlobalHeap()
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    msvcrt = ctypes.cdll.msvcrt

    monkeypatch.setattr(core, "_OpenClipboard", lambda value: 1)
    monkeypatch.setattr(user32, "EmptyClipboard", lambda: 1)
    monkeypatch.setattr(kernel32, "GlobalAlloc", fake.alloc)
    monkeypatch.setattr(kernel32, "GlobalLock", fake.lock)
    monkeypatch.setattr(kernel32, "GlobalUnlock", lambda handle: 1)
    monkeypatch.setattr(kernel32, "GlobalFree", lambda handle: 0)
    monkeypatch.setattr(user32, "CloseClipboard", lambda: 1)

    real_wcsncpy = msvcrt.wcsncpy

    def counting_wcsncpy(dst: object, src: object, count: object) -> object:
        fake.copy_count = count.value
        return real_wcsncpy(dst, src, count)

    monkeypatch.setattr(msvcrt, "wcsncpy", counting_wcsncpy)

    def fake_set_clipboard_data(format_: object, handle: object) -> int:
        fake.stored_format = format_.value
        return 1

    monkeypatch.setattr(user32, "SetClipboardData", fake_set_clipboard_data)
    return fake


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain ascii",
        f"{EARTH}{GRINNING}0123456789abcdefgh",  # 20 code points, 22 UTF-16 units
        f"tail is {EARTH}",
        EARTH * 40,
        "caf\u00e9 \u65e5\u672c\u8a9e",
        f"{EARTH}mixed\U0010fffd",
    ],
)
def test_clipboard_text_survives_the_copy_intact(heap: FakeGlobalHeap, text: str) -> None:
    assert core.SetClipboardText(text) is True

    assert heap.read_text() == text


def test_buffer_is_sized_in_utf16_units_with_room_for_the_terminator(
    heap: FakeGlobalHeap,
) -> None:
    text = f"{EARTH}{GRINNING}0123456789abcdefgh"

    core.SetClipboardText(text)

    units = len(text.encode("utf-16-le")) // 2
    assert units == 22
    assert len(text) == 20, "code points differ from UTF-16 units: that is the bug"
    assert heap.allocated_bytes == (units + 1) * 2
    assert heap.copy_count == units + 1


def test_copied_text_is_nul_terminated(heap: FakeGlobalHeap) -> None:
    text = f"{EARTH}{GRINNING}0123456789abcdefgh"

    core.SetClipboardText(text)

    assert heap.raw.endswith(b"\x00\x00")


def test_astral_tail_is_not_dropped(heap: FakeGlobalHeap) -> None:
    """The reported symptom: one trailing character lost per surrogate pair."""
    text = f"{EARTH}{GRINNING}0123456789abcdefgh"

    core.SetClipboardText(text)

    assert heap.read_text().endswith("gh")
