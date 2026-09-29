"""The pairing agent's gates: the window, HID-only, and the reply the app parses."""

from __future__ import annotations

import json

import pytest
from bt_joy_pairing import (
    BT_JOY_DEV,
    HID_UUID,
    JOY_NODE,
    TELEOP_NODE,
    pairing_allowed,
    pairing_reply,
    phone_teleop_params,
    selftest,
    service_allowed,
)


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


def test_the_phone_teleop_takes_the_generated_parameters_on_its_own_device():
    generated = {
        "a200_0553": {
            "teleop_twist_joy_node": {"ros__parameters": {"enable_button": 4, "scale_linear.x": 0.4}},
            "joy_node": {"ros__parameters": {"deadzone": 0.1, "autorepeat_rate": 20.0, "dev": "/dev/input/js0"}},
        }
    }
    params = phone_teleop_params(generated)["a200_0553"]
    assert params[JOY_NODE]["ros__parameters"] == {"deadzone": 0.1, "autorepeat_rate": 20.0, "dev": BT_JOY_DEV}
    assert params[TELEOP_NODE]["ros__parameters"] == {"enable_button": 4, "scale_linear.x": 0.4}
    # The generated file stays untouched: Clearpath's joy_node keeps reading js0.
    assert generated["a200_0553"]["joy_node"]["ros__parameters"]["dev"] == "/dev/input/js0"
