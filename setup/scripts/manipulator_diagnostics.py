#!/usr/bin/env python3
"""manipulator_diagnostics: feed UR5 + OnRobot RG6 into the Clearpath
diagnostics pipeline as ``diagnostic_msgs``.

Why this is needed
------------------
The ``diagnostic_aggregator`` subscribes to ``<ns>/diagnostics`` and fans the
result out to ``<ns>/diagnostics_agg`` -- the topic the Cockpit extension
reads over the foxglove_bridge.  The manipulator is missing from that chain
entirely:

* ``clearpath_generator_common`` only generates analyzers for platform (power,
  e-stop, drive) and sensors -- arm and gripper do not appear in the generator.
* The ``controller_manager`` of the arm publishes its diagnostics into the
  *manipulators* namespace (``/a200_0553/manipulators/diagnostics``), so NOT
  onto the topic the aggregator subscribes to.
* The ``ur_robot_driver`` does not publish mode/safety/external control as
  ``diagnostic_msgs`` at all, but as its own ``ur_dashboard_msgs``.
* The RG6 state arrives as JSON from ``rg6_grip_bridge`` on
  ``rg6/bridge_state``, not as a typed message.

This node translates all of that into ``diagnostic_msgs/DiagnosticArray``.
Together with the analyzer block that the boot patcher
(``clearpath-custom-setup.py``, step 6) writes into the generated
``diagnostic_aggregator.yaml``, the manipulator thereby appears in *every*
diagnostics consumer.

Delivered statuses (prefix = node name, as the analyzer expects it)
-------------------------------------------------------------------
``manipulator_diagnostics: Arm Mode``
    ``robot_mode`` + ``safety_mode`` (latched topics of the
    io_and_status_controller).
``manipulator_diagnostics: Arm Control``
    The *actual* health indicator: is the joint_state stream of the
    ``joint_state_broadcaster`` flowing?  It only flows with an active
    ros2_control hardware interface -- ``robot_program_running`` alone is NOT
    a valid signal (it stays true while the motion link is dead).
``manipulator_diagnostics: Arm Joints``
    Joint angles/velocities, rate, moving yes/no.
``manipulator_diagnostics: Arm Controllers``
    ``controller_manager/list_controllers`` -- which command controller is
    active, is one missing?
``manipulator_diagnostics: Gripper``
    RG6: width, force signal, grip_detected, busy, tool power, last command.

Invocation (service clearpath-custom-manipulator-diagnostics, see installer)::

    manipulator-diagnostics --ros-args -p manipulator_ns:=/a200_0553/manipulators

Selftest without ROS (pure evaluation logic -- runs on the workstation too)::

    python3 manipulator_diagnostics.py --selftest
"""

from __future__ import annotations

import math
import sys
from collections import deque, namedtuple

# --------------------------------------------------------------------------- #
# Pure evaluation logic (ROS-free, so it is testable without a robot)
# --------------------------------------------------------------------------- #

OK, WARN, ERROR, STALE = 0, 1, 2, 3

# "INACTIVE" (out of service, grey in Cockpit) is NOT a diagnostic_msgs level
# -- the standard only knows OK/WARN/ERROR/STALE.  An own byte value would
# confuse the max() rollups of the aggregator and every foreign consumer
# (rqt_robot_monitor).  Hence the convention: the level stays OK (nothing is
# broken, after all) plus the value 'display=inactive'.  Consumers that do not
# know the convention see "OK" with a plain-text message ("arm switched off")
# -- so nothing wrong; Cockpit paints it grey.
DISPLAY_KEY = "display"
DISPLAY_INACTIVE = "inactive"

Verdict = namedtuple("Verdict", "level message inactive")
Verdict.__new__.__defaults__ = (False,)


def inactive(message):
    """Out of service, not an error -- see DISPLAY_INACTIVE."""
    return Verdict(OK, message, True)


# ur_dashboard_msgs/RobotMode constants (duplicated here so the selftest runs
# without ROS; at runtime the real .msg constants are used).
ROBOT_MODE_NAMES = {
    -1: "NO_CONTROLLER",
    0: "DISCONNECTED",
    1: "CONFIRM_SAFETY",
    2: "BOOTING",
    3: "POWER_OFF",
    4: "POWER_ON",
    5: "IDLE",
    6: "BACKDRIVE",
    7: "RUNNING",
    8: "UPDATING_FIRMWARE",
}

SAFETY_MODE_NAMES = {
    1: "NORMAL",
    2: "REDUCED",
    3: "PROTECTIVE_STOP",
    4: "RECOVERY",
    5: "SAFEGUARD_STOP",
    6: "SYSTEM_EMERGENCY_STOP",
    7: "ROBOT_EMERGENCY_STOP",
    8: "VIOLATION",
    9: "FAULT",
    10: "VALIDATE_JOINT_ID",
    11: "UNDEFINED_SAFETY_MODE",
}

# Safety states that require intervention -> ERROR.
SAFETY_ERROR = {3, 5, 6, 7, 8, 9}
# Safety states that restrict operation -> WARN.
SAFETY_WARN = {2, 4, 10, 11}

# An e-stop can NOT be released by software -> its own plain-text message.
SAFETY_ESTOP = {6, 7}

# What went to the gripper last.  The bridge sends the plain text directly
# (rg6_grip_bridge.COMMAND_*); the numeric values are translated along so that
# archived recordings stay readable.
GRIPPER_COMMANDS = {0: "NONE", 1: "OPEN", 2: "CLOSE", 3: "GRIP"}

# robot_mode values in which the arm is powered -- and in which the 24 V tool
# supply of the RG6 CAN therefore be present at all (the gripper hangs off the
# UR tool connector).  BACKDRIVE (freedrive) counts: motors unpowered, but
# controller and tool connector supplied.
ARM_POWERED_MODES = {4, 5, 6, 7}  # POWER_ON, IDLE, BACKDRIVE, RUNNING

# POWER_OFF is an OPERATOR DECISION, not an error: the arm was switched off on
# purpose (maintenance/end of day).  Everything that follows from it -- no
# external control, no trustworthy joint values, an unpowered gripper -- is
# then as expected and is reported as "out of service" (grey), not as a
# warning.  The manipulators watchdog behaves the same way: at POWER_OFF no
# recovery runs.
ARM_OFF_MODE = 3  # POWER_OFF


def arm_is_powered(robot_mode):
    """Can there be any voltage at the tool connector? -> True/False/None."""
    if robot_mode is None:
        return None
    return robot_mode in ARM_POWERED_MODES


def arm_is_off(robot_mode):
    """Switched off on purpose (POWER_OFF)? -> bool."""
    return robot_mode == ARM_OFF_MODE


def robot_mode_name(mode):
    """Int -> plain text, unknown values stay readable."""
    if mode is None:
        return "UNKNOWN"
    return ROBOT_MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def safety_mode_name(mode):
    if mode is None:
        return "UNKNOWN"
    return SAFETY_MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def arm_mode_level(robot_mode, safety_mode):
    """Evaluation of robot_mode/safety_mode -> Verdict.

    Both topics are latched and only published on change -- a ``None``
    therefore means "never received" (driver/controller absent), not "stale".
    Hence STALE instead of ERROR: the information is missing, which does not
    necessarily mean the arm is broken.
    """
    if robot_mode is None and safety_mode is None:
        return Verdict(
            STALE,
            "no robot_mode/safety_mode received - is the "
            "io_and_status_controller running?",
        )

    rm, sm = robot_mode_name(robot_mode), safety_mode_name(safety_mode)

    if safety_mode in SAFETY_ESTOP:
        return Verdict(
            ERROR, f"emergency stop active ({sm}) - releasable only physically"
        )
    if safety_mode in SAFETY_ERROR:
        return Verdict(ERROR, f"safety stop: {sm} (robot_mode {rm})")
    if robot_mode is not None and robot_mode < 3:
        # NO_CONTROLLER / DISCONNECTED / CONFIRM_SAFETY: no connection to the
        # control box, or confirmation at the teach pendant required.
        return Verdict(ERROR, f"arm not reachable: {rm}")
    if safety_mode in SAFETY_WARN:
        return Verdict(WARN, f"safety restricted: {sm} (robot_mode {rm})")
    if robot_mode == 7:
        return Verdict(OK, f"{rm}, safety {sm}")
    if arm_is_off(robot_mode):
        # Switched off on purpose -> grey, no warning (see ARM_OFF_MODE).
        return inactive(f"arm switched off ({rm})")
    # BOOTING / POWER_ON / IDLE / BACKDRIVE / UPDATING_FIRMWARE: a transitional
    # or special state in which the arm is not ready to be driven from ROS.
    return Verdict(WARN, f"not ready to drive: {rm} (safety {sm})")


def arm_control_level(program_running, joint_state_age, timeout, arm_off=False):
    """Evaluation of the motion link -> Verdict.

    ``joint_state_age`` is the age of the last joint_states message carrying
    arm joints (``None`` = never received one).  That stream is the
    trustworthy signal: it only flows with an active ros2_control hardware
    interface, whereas ``program_running`` can wrongly stay true.

    With the arm switched off, BOTH are as expected -- turning that into a
    warning or even an error paints the panel red on a deliberately powered
    down arm.  The watchdog deliberately keeps its hands off at POWER_OFF too.
    """
    if arm_off:
        return inactive("arm switched off - external control stopped as expected")
    if joint_state_age is None:
        return Verdict(
            ERROR,
            "no joint_state stream from the arm - hardware interface "
            "not activated (arm powered up late? "
            "restart clearpath-manipulators)",
        )
    if joint_state_age > timeout:
        return Verdict(
            ERROR,
            f"joint_state stream silent for {joint_state_age:.1f}s "
            "- motion link dead",
        )
    if program_running is False:
        return Verdict(
            WARN, "external control not running (arm not commandable from ROS)"
        )
    if program_running is None:
        return Verdict(
            WARN, "external control status unknown (robot_program_running missing)"
        )
    return Verdict(OK, "external control active, joint_state stream running")


def arm_joints_level(joint_count, joint_state_age, timeout, arm_off=False):
    """Evaluation of the joint values -> Verdict.

    With the arm switched off the POSITIONS stay valid (absolute encoders),
    but velocity and effort are only noise -- measured up to 0.05 rad/s with
    the arm completely at rest.  Hence grey instead of green: the numbers are
    there, but "moving"/"at rest" says nothing.
    """
    if not joint_count or joint_state_age is None or joint_state_age > timeout:
        return Verdict(STALE, "no current joint values")
    if arm_off:
        return inactive(
            f"arm switched off - {joint_count} joints, "
            "values are the last encoder positions"
        )
    return Verdict(OK, f"{joint_count} joints")


def arm_controllers_level(controllers, required, arm_off=False):
    """Evaluation of list_controllers -> Verdict.

    ``controllers``: ``{name: state}`` or ``None`` (service unreachable).
    ``required``: controllers that MUST be active (broadcasters plus the
    default command controller).  Inactive command controllers are explicitly
    normal -- the controller_mode_manager keeps the mutually exclusive modes
    parked.

    Real controller problems stay WARN/ERROR even with the arm switched off
    (they concern the ROS side, not the power); only the good case turns grey,
    so that the arm tile shows "out of service" as a whole.
    """
    if controllers is None:
        return Verdict(STALE, "controller_manager/list_controllers unreachable")
    if not controllers:
        return Verdict(ERROR, "controller_manager knows no controllers")

    missing = [c for c in required if c not in controllers]
    stopped = [c for c in required if controllers.get(c) not in (None, "active")]
    if missing:
        return Verdict(ERROR, "controllers missing: " + ", ".join(sorted(missing)))
    if stopped:
        return Verdict(ERROR, "controllers not active: " + ", ".join(sorted(stopped)))

    unconfigured = sorted(
        n for n, s in controllers.items() if s not in ("active", "inactive")
    )
    if unconfigured:
        return Verdict(
            WARN, "controllers in unexpected state: " + ", ".join(unconfigured)
        )

    active = sorted(n for n, s in controllers.items() if s == "active")
    summary = f"{len(active)}/{len(controllers)} controllers active"
    if arm_off:
        return inactive(f"{summary} (arm switched off)")
    return Verdict(OK, summary)


#: Fields that ``rg6_grip_bridge.status_payload`` delivers, with the type they
#: must have.  What is missing becomes None -- a bridge that does not send a
#: field should empty only that row, not the whole panel.
BRIDGE_FIELDS = {
    "width_m": (int, float),
    "busy": bool,
    "grip_detected": bool,
    "status": int,
    "safety_failed": bool,
    "last_command": str,
}


def parse_bridge_state(data):
    """JSON from ``<ns>/rg6/bridge_state`` -> dict, or None if unusable.

    Why it is parsed at all:  ``rg6_grip_bridge`` reports the gripper state as
    JSON inside a ``std_msgs/String``, not as a typed message.  In exchange the
    string costs the type check a .msg gets for free, so that check lives here.

    None of this may raise:  a callback that dies on a foreign payload takes
    the whole diagnostics node with it -- and then the statement about the ARM
    is missing too, which has nothing to do with the gripper.
    """
    import json

    try:
        raw = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for name, want in BRIDGE_FIELDS.items():
        value = raw.get(name)
        if value is None:
            out[name] = None
        elif want is bool:
            out[name] = value if isinstance(value, bool) else None
        elif isinstance(value, bool):
            # In Python bool is an int subclass -- without this branch a
            # "width_m": true would pass as a number.
            out[name] = None
        else:
            out[name] = value if isinstance(value, want) else None
    if out["width_m"] is None and raw.get("width_m") is not None:
        return None  # a width that is not a number: unusable
    return out


def gripper_signal_valid(width_raw, force_raw, dead_threshold):
    """Does the RG6 deliver a valid tool signal at all? -> bool.

    The probe is the voltage against ``dead_input_threshold`` (0.2 V): with no
    24 V tool supply present, AI2 (width) and AI3 (force) drop to ~0.05 V.

    Why the VOLTAGE and not the answer of the XML-RPC endpoint:  the endpoint
    sits in the control box and answers even when nothing is powered at the
    tool connector.  It knows what it commanded last -- AI2/AI3 know what the
    hardware does.
    """
    if width_raw is None or force_raw is None:
        return False
    return width_raw >= dead_threshold or force_raw >= dead_threshold


def gripper_level(
    state_age, timeout, signal_valid, robot_mode, width_raw, dead_threshold
):
    """Evaluation of the RG6 state -> Verdict.

    The RG6 hangs off the UR tool connector: without a powered arm it cannot
    have any supply at all.  That is then not a gripper fault but a consequence
    of the arm state -- hence grey (arm deliberately off) or WARN (arm in a
    state in which it should be powered).
    """
    if state_age is None:
        return Verdict(ERROR, "no rg6/bridge_state - is rg6-grip-bridge running?")
    if state_age > timeout:
        # The bridge STAYS SILENT when the XML-RPC endpoint does not answer
        # (it prefers reporting nothing over an old value).  A status that is
        # too old is therefore exactly the signal for "endpoint gone".
        return Verdict(
            ERROR,
            f"rg6/bridge_state silent for {state_age:.1f}s - "
            "rg6-grip-bridge dead or URCap endpoint gone?",
        )

    if not signal_valid:
        raw = "n/a" if width_raw is None else f"{width_raw:.2f} V"
        if arm_is_off(robot_mode):
            return inactive(
                "arm switched off - gripper without supply " f"(tool signal {raw})"
            )
        if arm_is_powered(robot_mode) is False:
            return Verdict(
                WARN,
                f"arm not powered ({robot_mode_name(robot_mode)}) "
                f"- gripper without supply (tool signal {raw})",
            )
        # Arm powered, still no signal: the 24 V tool supply is not present.
        # Switching it on is the business of the OnRobot URCap -- the ROS route
        # there would go over a tool DO, and the URCap occupies that itself.  No
        # ROS service can repair this; the place to look is the teach pendant.
        return Verdict(
            WARN,
            f"no valid tool signal ({raw} < "
            f"{dead_threshold:.2f} V) - tool unpowered: "
            "is the URCap program running on the pendant?",
        )
    return Verdict(OK, "ready")


def gripper_summary(width_m, grip_detected, busy, stroke_m):
    """Short text for the OK message: 'open, 158mm (99%)' / 'grasped, 42mm'."""
    if width_m is None:
        return "width unknown"
    mm = width_m * 1000.0
    pct = 100.0 * width_m / stroke_m if stroke_m > 0.0 else 0.0
    if busy:
        state = "moving"
    elif grip_detected:
        state = "grasped"
    elif width_m >= 0.95 * stroke_m:
        state = "open"
    elif width_m <= 0.02:
        state = "closed"
    else:
        state = "part open"
    return f"{state}, {mm:.0f}mm ({pct:.0f}%)"


def selftest() -> int:
    """Sanity check of the evaluation logic (without ROS, without numpy).

    The gripper/POWER_OFF cases are exactly the values measured on the
    a200-0553 (2026-07-29): powered AI2 10.00 V / AI3 1.33 V, unpowered both
    ~0.056 V while tool_power_on=true, *_received=true, busy=true at the same
    time.
    """
    DEAD = 0.2

    # --- Arm Mode ---------------------------------------------------------
    assert arm_mode_level(7, 1).level == OK, "RUNNING/NORMAL must be OK"
    assert arm_mode_level(7, 2).level == WARN, "REDUCED -> WARN"
    assert arm_mode_level(7, 3).level == ERROR, "PROTECTIVE_STOP -> ERROR"
    assert arm_mode_level(0, 1).level == ERROR, "DISCONNECTED -> ERROR"
    assert arm_mode_level(None, None).level == STALE, "nothing received -> STALE"
    assert "emergency stop" in arm_mode_level(7, 7).message, "e-stop needs plain text"
    # Safety beats robot_mode: a p-stop while RUNNING stays ERROR.
    assert arm_mode_level(5, 8).level == ERROR, "VIOLATION -> ERROR"
    # POWER_OFF is an operator decision -> grey, not yellow.
    off = arm_mode_level(3, 1)
    assert off.inactive and off.level == OK, "POWER_OFF -> inactive (grey), not WARN"
    assert arm_mode_level(4, 1).level == WARN, "POWER_ON (transition) -> WARN"
    assert arm_mode_level(5, 1).level == WARN, "IDLE (transition) -> WARN"
    # A safety problem stays visible even while the arm is switched off.
    assert arm_mode_level(3, 8).level == ERROR, "VIOLATION beats POWER_OFF"

    # --- Arm Control ------------------------------------------------------
    assert arm_control_level(True, 0.01, 2.0).level == OK
    assert arm_control_level(False, 0.01, 2.0).level == WARN, "EC off -> WARN"
    assert arm_control_level(True, 5.0, 2.0).level == ERROR, "stream broken -> ERROR"
    # Exactly watchdog case (b): EC reports 'running', the motion link is dead.
    assert arm_control_level(True, None, 2.0).level == ERROR, "never a JS -> ERROR"
    assert arm_control_level(None, 0.01, 2.0).level == WARN
    # With the arm switched off, "EC stopped" is as expected -- and a dead
    # joint_state stream is not an error either (the watchdog rests too).
    assert arm_control_level(False, 0.01, 2.0, arm_off=True).inactive
    assert arm_control_level(False, None, 2.0, arm_off=True).inactive

    # --- Arm Joints -------------------------------------------------------
    assert arm_joints_level(6, 0.01, 2.0).level == OK
    assert arm_joints_level(6, 5.0, 2.0).level == STALE
    assert arm_joints_level(0, 0.01, 2.0).level == STALE
    assert arm_joints_level(6, 0.01, 2.0, arm_off=True).inactive, "arm off -> grey"

    # --- Arm Controllers --------------------------------------------------
    req = ["joint_state_broadcaster", "arm_0_joint_trajectory_controller"]
    all_ok = {
        "joint_state_broadcaster": "active",
        "arm_0_joint_trajectory_controller": "active",
        "freedrive_mode_controller": "inactive",
    }
    assert arm_controllers_level(all_ok, req).level == OK, "parked modes are normal"
    missing = dict(all_ok)
    del missing["joint_state_broadcaster"]
    assert arm_controllers_level(missing, req).level == ERROR
    stopped = dict(all_ok, joint_state_broadcaster="inactive")
    assert arm_controllers_level(stopped, req).level == ERROR
    weird = dict(all_ok, freedrive_mode_controller="unconfigured")
    assert arm_controllers_level(weird, req).level == WARN
    assert arm_controllers_level(None, req).level == STALE
    assert arm_controllers_level(all_ok, req, arm_off=True).inactive
    # A real controller problem stays red even with the arm switched off.
    assert arm_controllers_level(stopped, req, arm_off=True).level == ERROR

    # --- Gripper: signal validity -----------------------------------------
    assert gripper_signal_valid(10.0, 1.334, DEAD), "powered (measured)"
    assert not gripper_signal_valid(0.056, 0.053, DEAD), "unpowered (measured)"
    assert not gripper_signal_valid(0.0, 0.0, DEAD), "arm POWER_OFF (measured)"
    assert not gripper_signal_valid(None, None, DEAD)
    # Gripper fully closed: AI2 drops to the calibration lower bound (0.56 V)
    # but stays above the dead threshold -- must NOT count as unpowered.
    assert gripper_signal_valid(0.56, 0.9, DEAD), "a closed gripper is not dead"

    # --- Gripper: state from the bridge ------------------------------------
    # The gripper state arrives as JSON from rg6_grip_bridge.
    good = parse_bridge_state(
        '{"width_m": 0.1032, "busy": false, "grip_detected": true,'
        ' "status": 0, "safety_failed": false, "last_command": "GRIP"}'
    )
    assert good["width_m"] == 0.1032 and good["grip_detected"] is True, good
    # A broken or foreign payload must NOT kill the node -- it is the same as
    # "no status": better report grey/red than crash.
    assert parse_bridge_state("not json") is None
    assert parse_bridge_state("[1, 2, 3]") is None
    assert parse_bridge_state('{"width_m": "wide"}') is None, "width must be a number"
    # Missing fields are allowed and become None -- a bridge that does not send
    # a field should not empty the panel.
    assert parse_bridge_state('{"width_m": 0.05}')["busy"] is None

    # --- Gripper: evaluation ----------------------------------------------
    assert gripper_level(0.05, 2.0, True, 7, 10.0, DEAD).level == OK
    stale = gripper_level(9.0, 2.0, True, 7, 10.0, DEAD)
    assert stale.level == ERROR and "bridge" in stale.message, stale.message
    never = gripper_level(None, 2.0, True, 7, None, DEAD)
    assert never.level == ERROR and "bridge" in never.message, never.message
    # THE case from the bug report: arm POWER_OFF, gripper without supply.
    dead_off = gripper_level(0.05, 2.0, False, 3, 0.0, DEAD)
    assert dead_off.inactive and dead_off.level == OK, "arm off -> gripper grey, not OK"
    assert "switched off" in dead_off.message
    # Arm powered, gripper still without signal -> a real warning with a recipe.
    dead_on = gripper_level(0.05, 2.0, False, 7, 0.056, DEAD)
    assert dead_on.level == WARN and not dead_on.inactive
    # The URCap sets the tool voltage, no ROS service does -- so the warning
    # must point at the pendant and must not name a service.
    assert "URCap" in dead_on.message, "the warning must name the way out"
    assert "set_tool_power" not in dead_on.message, "no such service exists"
    # Arm in an unpowered non-POWER_OFF state (e.g. BOOTING).
    assert gripper_level(0.05, 2.0, False, 2, 0.0, DEAD).level == WARN

    assert "open" in gripper_summary(0.159, False, False, 0.160)
    assert "closed" in gripper_summary(0.0, False, False, 0.160)
    assert "grasped" in gripper_summary(0.042, True, False, 0.160)
    assert "moving" in gripper_summary(0.042, False, True, 0.160)
    assert gripper_summary(None, False, False, 0.160) == "width unknown"

    # --- arm state --------------------------------------------------------
    assert arm_is_powered(7) and arm_is_powered(6) and arm_is_powered(4)
    assert not arm_is_powered(3) and not arm_is_powered(2)
    assert arm_is_powered(None) is None
    assert arm_is_off(3) and not arm_is_off(7)

    print(
        "manipulator_diagnostics selftest: OK "
        f"({len(ROBOT_MODE_NAMES)} robot_modes, {len(SAFETY_MODE_NAMES)} safety_modes)"
    )
    return 0


# --------------------------------------------------------------------------- #
# ROS node (only imported when not running --selftest)
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()

    import time

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool, String

    # Optional dependencies: if one is missing, ONLY the affected status drops
    # out (with plain text), the rest keeps running.  That keeps the node
    # startable on a robot without the RG6 workspace.
    try:
        from ur_dashboard_msgs.msg import RobotMode, SafetyMode

        UR_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover - depends on the installation
        RobotMode = SafetyMode = None
        UR_MSGS_ERROR = str(exc)

    # ToolDataMsg carries AI2/AI3 and the tool voltage -- the only gripper
    # numbers that do NOT come from the bridge.  rg6_msgs/GripperState is
    # deliberately absent: that package is not in the boot path of the robot,
    # and the state arrives as JSON from rg6_grip_bridge.
    try:
        from ur_msgs.msg import ToolDataMsg

        TOOL_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover
        ToolDataMsg = None
        TOOL_MSGS_ERROR = str(exc)

    try:
        from controller_manager_msgs.srv import ListControllers

        CM_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover
        ListControllers = None
        CM_MSGS_ERROR = str(exc)

    # Latched (transient_local) + publish-on-change: exactly how the
    # gpio_controller publishes robot_mode/safety_mode/robot_program_running.  A
    # VOLATILE subscriber would miss the current value at startup and stay blind
    # until the next change.
    LATCHED = QoSProfile(
        depth=1,
        history=HistoryPolicy.KEEP_LAST,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    def kv(values):
        """dict -> KeyValue[]; everything as a string, as diagnostic_msgs wants."""
        return [KeyValue(key=str(k), value=str(v)) for k, v in values.items()]

    # DiagnosticStatus.level is a 'byte' in the .msg -- rosidl_generator_py maps
    # that onto a bytes object of length 1, NOT onto int.  Instead of guessing,
    # it is read off the real constant (which also holds if a future distro
    # changes it).
    LEVEL_AS_BYTES = isinstance(DiagnosticStatus.OK, bytes)

    def level_field(level):
        return bytes([int(level)]) if LEVEL_AS_BYTES else int(level)

    class ManipulatorDiagnostics(Node):
        def __init__(self) -> None:
            super().__init__("manipulator_diagnostics")

            ns = self.declare_parameter(
                "manipulator_ns", "/a200_0553/manipulators"
            ).value.rstrip("/")
            self.diagnostics_topic = self.declare_parameter(
                "diagnostics_topic", "/a200_0553/diagnostics"
            ).value
            self.rate_hz = float(self.declare_parameter("rate_hz", 1.0).value)
            self.arm_prefix = self.declare_parameter("arm_prefix", "arm_0_").value
            self.robot_ip = self.declare_parameter("robot_ip", "192.168.131.40").value
            # The joint_state stream runs at 125 Hz; 2 s of tolerance covers a
            # zenoh hiccup without masking a real breakdown.
            self.js_timeout = float(
                self.declare_parameter("joint_state_timeout", 2.0).value
            )
            self.gripper_timeout = float(
                self.declare_parameter("gripper_timeout", 2.0).value
            )
            self.stroke_m = float(self.declare_parameter("stroke_m", 0.160).value)
            # Below this voltage the RG6 delivers no valid tool signal
            # (measured 2026-07-29: powered AI2 10.00 V, unpowered ~0.056 V).
            self.dead_input_threshold = float(
                self.declare_parameter("dead_input_threshold", 0.2).value
            )
            # Noise of the joint velocity on a STANDING arm: powered exactly
            # 0.0000, unpowered up to 0.055 rad/s measured.  The threshold only
            # covers the powered case -- unpowered, "moving" is suppressed
            # anyway (the status is 'out of service' then).
            self.motion_eps = float(
                self.declare_parameter("motion_eps_rad_s", 0.02).value
            )
            self.required_controllers = list(
                self.declare_parameter(
                    "required_controllers",
                    [
                        "joint_state_broadcaster",
                        "arm_0_joint_trajectory_controller",
                        "io_and_status_controller",
                    ],
                ).value
            )
            self.controller_poll_s = float(
                self.declare_parameter("controller_poll_period", 5.0).value
            )
            self.arm_hardware_id = self.declare_parameter(
                "arm_hardware_id", f"UR5 CB3 @ {self.robot_ip}"
            ).value
            self.gripper_hardware_id = self.declare_parameter(
                "gripper_hardware_id", "OnRobot RG6 @ UR Tool-I/O"
            ).value

            # ---- state ---------------------------------------------------
            self._robot_mode = None
            self._safety_mode = None
            self._program_running = None
            self._js_stamps = deque(maxlen=64)  # monotonic receive times (arm)
            self._joints = {}  # short name -> (pos, vel, eff)
            self._gripper = None  # last bridge state (dict)
            self._gripper_time = None
            self._tool = None  # last ToolDataMsg (AI2/AI3)
            self._controllers = None  # {name: state} | None
            self._controllers_time = None
            self._cm_future = None

            # ---- Subscriptions -------------------------------------------
            if RobotMode is not None:
                self.create_subscription(
                    RobotMode,
                    f"{ns}/io_and_status_controller/robot_mode",
                    self._on_robot_mode,
                    LATCHED,
                )
                self.create_subscription(
                    SafetyMode,
                    f"{ns}/io_and_status_controller/safety_mode",
                    self._on_safety_mode,
                    LATCHED,
                )
            self.create_subscription(
                Bool,
                f"{ns}/io_and_status_controller/robot_program_running",
                self._on_program_running,
                LATCHED,
            )
            self.create_subscription(
                JointState, f"{ns}/joint_states", self._on_joint_states, 10
            )
            self.create_subscription(
                String, f"{ns}/rg6/bridge_state", self._on_gripper, 10
            )
            if ToolDataMsg is not None:
                self.create_subscription(
                    ToolDataMsg,
                    f"{ns}/io_and_status_controller/tool_data",
                    self._on_tool_data,
                    10,
                )

            # ---- controller_manager --------------------------------------
            self._cm_client = None
            if ListControllers is not None:
                self._cm_client = self.create_client(
                    ListControllers, f"{ns}/controller_manager/list_controllers"
                )
                self.create_timer(self.controller_poll_s, self._poll_controllers)

            # ---- output --------------------------------------------------
            self._pub = self.create_publisher(
                DiagnosticArray, self.diagnostics_topic, 10
            )
            self.create_timer(1.0 / max(self.rate_hz, 0.1), self._tick)

            self.get_logger().info(
                f"manipulator_diagnostics: {ns} -> {self.diagnostics_topic} "
                f"@ {self.rate_hz:.1f} Hz"
            )
            for missing, what in (
                (UR_MSGS_ERROR, "ur_dashboard_msgs"),
                (TOOL_MSGS_ERROR, "ur_msgs"),
                (CM_MSGS_ERROR, "controller_manager_msgs"),
            ):
                if missing:
                    self.get_logger().error(
                        f"{what} not importable ({missing}) - the corresponding "
                        "status reports that as an error. Workspace sourced?"
                    )

        # ---- Callbacks ---------------------------------------------------
        def _on_robot_mode(self, msg) -> None:
            self._robot_mode = int(msg.mode)

        def _on_safety_mode(self, msg) -> None:
            self._safety_mode = int(msg.mode)

        def _on_program_running(self, msg: Bool) -> None:
            self._program_running = bool(msg.data)

        def _on_joint_states(self, msg: JointState) -> None:
            """Count arm joints only.

            TWO sources sit on ``<ns>/joint_states``: the arm JSB and the
            finger value of the gripper bridge.  For judging the motion link
            only the arm stream counts -- the bridge keeps polling its XML-RPC
            endpoint even when the arm hardware interface is dead, and would
            otherwise mask a breakdown.
            """
            found = False
            for i, name in enumerate(msg.name):
                if not name.startswith(self.arm_prefix):
                    continue
                found = True
                self._joints[name[len(self.arm_prefix) :]] = (
                    msg.position[i] if i < len(msg.position) else float("nan"),
                    msg.velocity[i] if i < len(msg.velocity) else float("nan"),
                    msg.effort[i] if i < len(msg.effort) else float("nan"),
                )
            if found:
                self._js_stamps.append(time.monotonic())

        def _on_gripper(self, msg) -> None:
            """JSON from rg6_grip_bridge.  Garbage does NOT change the state.

            The old timestamp then stays and ages -- so the panel reports
            "silent" instead of "OK with nonsense", and that is the right
            statement: an unreadable payload is not a state.
            """
            state = parse_bridge_state(msg.data)
            if state is None:
                self.get_logger().warn(
                    f"unreadable rg6/bridge_state: {msg.data[:120]!r}",
                    throttle_duration_sec=10.0,
                )
                return
            self._gripper = state
            self._gripper_time = time.monotonic()

        def _on_tool_data(self, msg) -> None:
            self._tool = msg

        def _poll_controllers(self) -> None:
            """Query list_controllers asynchronously (never block in the timer)."""
            if self._cm_future is not None and not self._cm_future.done():
                return  # the previous call still hangs -> the service is gone
            if not self._cm_client.service_is_ready():
                self._controllers = None
                return
            self._cm_future = self._cm_client.call_async(ListControllers.Request())
            self._cm_future.add_done_callback(self._on_controllers)

        def _on_controllers(self, future) -> None:
            try:
                result = future.result()
            except Exception as exc:  # defensive: never let the service callback die
                self.get_logger().warning(
                    f"list_controllers failed: {exc}",
                    throttle_duration_sec=30.0,
                )
                self._controllers = None
                return
            self._controllers = {c.name: c.state for c in result.controller}
            self._controllers_time = time.monotonic()

        # ---- building the statuses ---------------------------------------
        def _age(self, stamp):
            return None if stamp is None else time.monotonic() - stamp

        def _joint_state_age(self):
            return self._age(self._js_stamps[-1] if self._js_stamps else None)

        def _joint_state_rate(self):
            """Rate from the time window of the last messages (0.0 = unknown)."""
            if len(self._js_stamps) < 2:
                return 0.0
            span = self._js_stamps[-1] - self._js_stamps[0]
            return (len(self._js_stamps) - 1) / span if span > 0.0 else 0.0

        def _status(self, name, verdict, hardware_id, values):
            """Verdict + values -> DiagnosticStatus.

            'inactive' travels as a value (see DISPLAY_INACTIVE), not as an own
            level -- the level stays standard conformant.
            """
            status = DiagnosticStatus()
            status.name = f"{self.get_name()}: {name}"
            status.level = level_field(verdict.level)
            status.message = verdict.message
            status.hardware_id = hardware_id
            if verdict.inactive:
                values = dict(values, **{DISPLAY_KEY: DISPLAY_INACTIVE})
            status.values = kv(values)
            return status

        def _arm_off(self):
            return arm_is_off(self._robot_mode)

        def _arm_mode_status(self):
            if RobotMode is None:
                return self._status(
                    "Arm Mode",
                    Verdict(ERROR, f"ur_dashboard_msgs missing ({UR_MSGS_ERROR})"),
                    self.arm_hardware_id,
                    {},
                )
            verdict = arm_mode_level(self._robot_mode, self._safety_mode)
            powered = arm_is_powered(self._robot_mode)
            return self._status(
                "Arm Mode",
                verdict,
                self.arm_hardware_id,
                {
                    "robot_mode": robot_mode_name(self._robot_mode),
                    "robot_mode_id": self._robot_mode,
                    "safety_mode": safety_mode_name(self._safety_mode),
                    "safety_mode_id": self._safety_mode,
                    # Derived for the UI: co-decides the gripper display.
                    "arm_powered": (
                        "unknown" if powered is None else str(powered).lower()
                    ),
                    "robot_ip": self.robot_ip,
                },
            )

        def _arm_control_status(self):
            age = self._joint_state_age()
            verdict = arm_control_level(
                self._program_running, age, self.js_timeout, arm_off=self._arm_off()
            )
            return self._status(
                "Arm Control",
                verdict,
                self.arm_hardware_id,
                {
                    "external_control": {
                        True: "running",
                        False: "stopped",
                        None: "unknown",
                    }[self._program_running],
                    "joint_state_rate_hz": f"{self._joint_state_rate():.1f}",
                    "joint_state_age_s": "never" if age is None else f"{age:.2f}",
                    "joint_state_timeout_s": f"{self.js_timeout:.1f}",
                    "motion_interface": (
                        "live" if age is not None and age <= self.js_timeout else "dead"
                    ),
                },
            )

        def _arm_joints_status(self):
            age = self._joint_state_age()
            arm_off = self._arm_off()
            verdict = arm_joints_level(
                len(self._joints), age, self.js_timeout, arm_off=arm_off
            )
            if verdict.level == STALE:
                return self._status(
                    "Arm Joints",
                    verdict,
                    self.arm_hardware_id,
                    {
                        "joints": "",
                        "joint_state_age_s": "never" if age is None else f"{age:.2f}",
                    },
                )

            values = {"joints": ", ".join(self._joints)}
            moving = False
            for short, (pos, vel, eff) in self._joints.items():
                values[f"{short}_rad"] = f"{pos:.4f}"
                values[f"{short}_deg"] = f"{math.degrees(pos):.1f}"
                values[f"{short}_vel_rad_s"] = f"{vel:.4f}"
                if math.isfinite(eff):
                    values[f"{short}_effort"] = f"{eff:.2f}"
                if math.isfinite(vel) and abs(vel) > self.motion_eps:
                    moving = True
            # On an unpowered arm the velocity is pure noise -- the statement
            # about motion would be made up.
            values["moving"] = "unknown" if arm_off else str(moving).lower()
            values["rate_hz"] = f"{self._joint_state_rate():.1f}"
            if not arm_off:
                verdict = Verdict(
                    verdict.level,
                    f"{verdict.message}, " + ("moving" if moving else "at rest"),
                )
            return self._status("Arm Joints", verdict, self.arm_hardware_id, values)

        def _arm_controllers_status(self):
            if ListControllers is None:
                return self._status(
                    "Arm Controllers",
                    Verdict(
                        ERROR, f"controller_manager_msgs missing ({CM_MSGS_ERROR})"
                    ),
                    self.arm_hardware_id,
                    {},
                )
            verdict = arm_controllers_level(
                self._controllers, self.required_controllers, arm_off=self._arm_off()
            )
            values = {"required": ", ".join(self.required_controllers)}
            if self._controllers:
                values.update(self._controllers)
                active = [
                    n
                    for n, s in self._controllers.items()
                    if s == "active" and n not in self.required_controllers
                ]
                values["active_optional"] = ", ".join(sorted(active)) or "-"
            return self._status(
                "Arm Controllers", verdict, self.arm_hardware_id, values
            )

        def _gripper_status(self):
            """Two sources, deliberately kept apart.

            The STATE (width, busy, grip_detected) comes from the bridge and
            thus from the device itself.  The VOLTAGES AI2/AI3 come from
            ``tool_data`` and answer a different question: is there any supply
            at the tool connector at all?  Merging them here would make the AI2
            curve -- measured on 2026-08-19 as mis-calibrated by up to 17 mm
            (R19) -- a width source again.
            """
            unknown = "unknown"
            age = self._age(self._gripper_time)
            state = self._gripper
            tool = self._tool
            dead = self.dead_input_threshold
            width_raw = None if tool is None else float(tool.analog_input2)
            force_raw = None if tool is None else float(tool.analog_input3)
            # Base validity exclusively on the analog signal: it is the only
            # HARDWARE feedback about the tool supply.
            valid = gripper_signal_valid(width_raw, force_raw, dead)
            verdict = gripper_level(
                age, self.gripper_timeout, valid, self._robot_mode, width_raw, dead
            )
            if state is None:
                return self._status(
                    "Gripper",
                    verdict,
                    self.gripper_hardware_id,
                    {
                        "state_age_s": "never",
                        "width_raw_v": (
                            unknown if width_raw is None else f"{width_raw:.3f}"
                        ),
                    },
                )

            width = state["width_m"] if valid else None
            if verdict.level == OK and not verdict.inactive:
                verdict = Verdict(
                    verdict.level,
                    gripper_summary(
                        width, state["grip_detected"], state["busy"], self.stroke_m
                    ),
                )
            last = state["last_command"]
            values = {
                "width_m": unknown if width is None else f"{width:.4f}",
                "width_mm": unknown if width is None else f"{width * 1000.0:.1f}",
                "width_percent": (
                    unknown
                    if width is None or self.stroke_m <= 0.0
                    else f"{100.0 * width / self.stroke_m:.0f}"
                ),
                "stroke_mm": f"{self.stroke_m * 1000.0:.0f}",
                # Always show the raw values: they are the diagnosis itself.
                # They do NOT come from the same source as the width -- which is
                # what makes them useful as a cross-check.
                "width_raw_v": unknown if width_raw is None else f"{width_raw:.3f}",
                "force_raw_v": unknown if force_raw is None else f"{force_raw:.3f}",
                "signal_valid": str(valid).lower(),
                "dead_input_threshold_v": f"{dead:.2f}",
                # Without tool voltage the device reports nothing trustworthy either.
                "grip_detected": (
                    unknown
                    if not valid or state["grip_detected"] is None
                    else str(state["grip_detected"]).lower()
                ),
                "busy": (
                    unknown
                    if not valid or state["busy"] is None
                    else str(state["busy"]).lower()
                ),
                # Device status, straight from the endpoint (rg_get_status /
                # rg_get_safety_failed).
                "device_status": (
                    unknown if state["status"] is None else str(state["status"])
                ),
                "safety_failed": (
                    unknown
                    if state["safety_failed"] is None
                    else str(state["safety_failed"]).lower()
                ),
                "last_command": (
                    unknown if last is None else GRIPPER_COMMANDS.get(last, str(last))
                ),
                # REAL hardware feedback: the measured voltage, not a commanded
                # setpoint.
                "tool_output_voltage_v": (
                    unknown
                    if tool is None
                    else f"{float(tool.tool_output_voltage):.0f}"
                ),
                "state_age_s": f"{age:.2f}",
            }
            return self._status("Gripper", verdict, self.gripper_hardware_id, values)

        def _tick(self) -> None:
            array = DiagnosticArray()
            array.header.stamp = self.get_clock().now().to_msg()
            array.status = [
                self._arm_mode_status(),
                self._arm_control_status(),
                self._arm_joints_status(),
                self._arm_controllers_status(),
                self._gripper_status(),
            ]
            self._pub.publish(array)

    rclpy.init()
    node = ManipulatorDiagnostics()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # normal stop (Ctrl+C / systemd)
    except Exception:
        # SIGTERM shutdown race as in octomap_feed: rclpy's signal handler
        # invalidates the context while spin is still building a wait set.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
