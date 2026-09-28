"""The wakeup command verifies feedback before creating a motion client."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/wakeup.sh"
JOINTS = [f"joint_{i}" for i in range(6)]


class MotionClientReached(Exception):
    """Stop the fake execution before it can create or send a goal."""


def _run_motion_block(monkeypatch, feedback, *, check=True):
    closed = []

    class Node:
        def __init__(self, name):
            self.ticks = 0

        def create_subscription(self, message_type, topic, callback, depth):
            if feedback is not None:
                names, positions = feedback
                callback(SimpleNamespace(joint_names=names, actual=SimpleNamespace(positions=positions)))

        def get_clock(self):
            return self

        def now(self):
            self.ticks += 1
            return SimpleNamespace(nanoseconds=self.ticks * 6_000_000_000)

        def destroy_node(self):
            closed.append("node")

    def action_client(*args):
        raise MotionClientReached

    modules = {
        "rclpy": {
            "init": lambda: None,
            "shutdown": lambda: closed.append("rclpy"),
            "spin_once": lambda *args, **kwargs: None,
        },
        "rclpy.node": {"Node": Node},
        "rclpy.action": {"ActionClient": action_client},
        "control_msgs.action": {"FollowJointTrajectory": object},
        "control_msgs.msg": {"JointTrajectoryControllerState": object},
        "trajectory_msgs.msg": {"JointTrajectory": object, "JointTrajectoryPoint": object},
        "builtin_interfaces.msg": {"Duration": object},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    values = {
        "ARM_ACTION": "/fake/move",
        "ARM_STATE_TOPIC": "/fake/state",
        "ARM_JOINTS_CSV": ",".join(JOINTS),
        "TARGET_JOINTS_CSV": "0,0,0,0,0,0",
        "PACKED_JOINTS_CSV": "0,0,0,0,0,0",
        "ARM_TIME": "10",
        "GOAL_TIMEOUT": "60",
        "START_TOL": "0.35",
        "CHECK_START": str(int(check)),
        "POSE_NAME": "home",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    source = re.search(r"^python3 - <<'PY'\n(.*?)^PY$", SCRIPT.read_text(), re.MULTILINE | re.DOTALL).group(1)
    try:
        exec(compile(source, str(SCRIPT), "exec"), {})
    except SystemExit as exc:
        assert exc.code == 1
        assert closed == ["node", "rclpy"]
        return
    pytest.fail("invalid feedback must stop before creating a motion client")


@pytest.mark.parametrize(
    "feedback",
    [
        None,
        (JOINTS[:5], [0.0] * 5),
        (JOINTS, [0.0] * 5),
        (JOINTS, [float("nan")] + [0.0] * 5),
        (JOINTS, [float("inf")] + [0.0] * 5),
        (JOINTS, [0.5] + [0.0] * 5),
    ],
)
def test_unverified_start_never_creates_a_motion_client(monkeypatch, feedback):
    _run_motion_block(monkeypatch, feedback)


def test_verified_start_can_reach_the_motion_client(monkeypatch):
    with pytest.raises(MotionClientReached):
        _run_motion_block(monkeypatch, (list(reversed(JOINTS)), [0.0] * 6))


@pytest.mark.parametrize("feedback", [None, (JOINTS[:5], [0.0] * 5), (JOINTS, [1.0] * 6)])
def test_from_any_preserves_the_explicit_override(monkeypatch, feedback):
    with pytest.raises(MotionClientReached):
        _run_motion_block(monkeypatch, feedback, check=False)
