"""The pairing agent's gates: the window, HID-only, and the reply the app parses."""

from __future__ import annotations

import json

import pytest
from bt_joy_pairing import HID_UUID, pairing_allowed, pairing_reply, selftest, service_allowed


def test_pairing_only_inside_the_window():
    assert pairing_allowed(now_s=100.0, window_end_s=160.0)
    assert not pairing_allowed(now_s=160.0, window_end_s=160.0)
    # No window was ever opened: the end is at zero on the monotonic clock.
    assert not pairing_allowed(now_s=5.0, window_end_s=0.0)


@pytest.mark.parametrize(
    ("uuid", "paired", "allowed"),
    [
        (HID_UUID, True, True),
        (HID_UUID.upper(), True, True),
        (HID_UUID, False, False),
        ("0000110b-0000-1000-8000-00805f9b34fb", True, False),  # A2DP sink
        ("00001105-0000-1000-8000-00805f9b34fb", True, False),  # OBEX object push
    ],
)
def test_only_hid_from_a_paired_device(uuid, paired, allowed):
    assert service_allowed(uuid, paired) is allowed


def test_reply_carries_the_address_the_app_bonds_to():
    reply = json.loads(pairing_reply("AA:BB:CC:DD:EE:FF", "cpr-a200-0553", 60.0))
    assert reply == {"address": "AA:BB:CC:DD:EE:FF", "name": "cpr-a200-0553", "window_s": 60.0}


def test_selftest_passes():
    assert selftest() == 0
