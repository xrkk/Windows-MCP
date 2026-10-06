"""Typing text that the 16-bit keyboard input struct cannot hold directly.

KEYBDINPUT.wScan is a WORD, so a code point above U+FFFF has to be sent as its
two UTF-16 surrogate halves (#436) -- sending ord(char) truncates it to the low
16 bits and types a private-use character instead. Empty text used to reach the
SendKeys parser and raise IndexError (#438).
"""

import pytest

from windows_mcp.uia import core
from windows_mcp.uia.enums import KeyboardEventFlag

KEY_DOWN = KeyboardEventFlag.KeyUnicode | KeyboardEventFlag.KeyDown
KEY_UP = KeyboardEventFlag.KeyUnicode | KeyboardEventFlag.KeyUp

EARTH = "\U0001f30d"  # U+1F30D, surrogate pair D83C DF0D
GRINNING = "\U0001f600"  # U+1F600, surrogate pair D83D DE00


@pytest.fixture
def key_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int, int]]:
    """Record (wVk, wScan, dwFlags) per event instead of injecting real input."""
    recorded: list[tuple[int, int, int]] = []

    def fake_send_input(*inputs: object) -> int:
        for item in inputs:
            recorded.append((item.union.ki.wVk, item.union.ki.wScan, item.union.ki.dwFlags))
        return len(inputs)

    monkeypatch.setattr(core, "SendInput", fake_send_input)
    return recorded


@pytest.mark.parametrize(
    ("char", "high", "low"),
    [
        (EARTH, 0xD83C, 0xDF0D),
        (GRINNING, 0xD83D, 0xDE00),
        ("\U0010fffd", 0xDBFF, 0xDFFD),  # last assignable code point
    ],
)
def test_astral_char_is_sent_as_both_surrogate_halves(
    key_events: list[tuple[int, int, int]],
    char: str,
    high: int,
    low: int,
) -> None:
    core.SendUnicodeChar(char)

    assert key_events == [
        (0, high, KEY_DOWN),
        (0, high, KEY_UP),
        (0, low, KEY_DOWN),
        (0, low, KEY_UP),
    ]


def test_astral_char_is_not_truncated_to_its_low_16_bits(
    key_events: list[tuple[int, int, int]],
) -> None:
    core.SendUnicodeChar(EARTH)

    truncated = ord(EARTH) & 0xFFFF
    assert all(scan != truncated for _, scan, _ in key_events)


def test_astral_char_bypasses_the_keyboard_layout_path(
    key_events: list[tuple[int, int, int]],
) -> None:
    """VkKeyScanW cannot represent a non-BMP char, so charMode must not matter."""
    core.SendUnicodeChar(EARTH, charMode=False)

    assert key_events == [
        (0, 0xD83C, KEY_DOWN),
        (0, 0xD83C, KEY_UP),
        (0, 0xDF0D, KEY_DOWN),
        (0, 0xDF0D, KEY_UP),
    ]


@pytest.mark.parametrize("char", ["a", "Z", "7", "é", "日", "\ufffd"])
def test_bmp_char_still_sends_one_event_pair(
    key_events: list[tuple[int, int, int]],
    char: str,
) -> None:
    core.SendUnicodeChar(char)

    assert key_events == [
        (0, ord(char), KEY_DOWN),
        (0, ord(char), KEY_UP),
    ]


def test_send_keys_with_empty_text_is_a_noop(
    key_events: list[tuple[int, int, int]],
) -> None:
    assert core.SendKeys("", waitTime=0) is None
    assert key_events == []


def test_send_keys_still_types_ordinary_text(
    key_events: list[tuple[int, int, int]],
) -> None:
    core.SendKeys("ab", interval=0, waitTime=0)

    assert [scan for _, scan, _ in key_events] == [ord("a"), ord("a"), ord("b"), ord("b")]


def test_send_keys_types_an_astral_char_through_the_surrogate_path(
    key_events: list[tuple[int, int, int]],
) -> None:
    core.SendKeys(EARTH, interval=0, waitTime=0)

    assert [scan for _, scan, _ in key_events] == [0xD83C, 0xD83C, 0xDF0D, 0xDF0D]
