#!/usr/bin/env python3
"""Custom Clearpath setup: patch generated config files after generation,
before the sub-services read them.

The numbering starts at 2 and is kept stable: whatever moves out of here into
robot.yaml leaves its number behind, so references to a step (the watchdog names
step 3) keep pointing at the same thing.  main() lists what left and where to.

Patches:
  2. Sensor mesh URIs file:// -> package:// (run_sensor_mesh_uri_patch).

  3. Arm JSB joint_states -> manipulators/joint_states (move_arm_joint_states)
     in /opt/ros/*/share/clearpath_manipulators/launch/control.launch.py.
     Detaches the arm joints from the platform namespace; a relay + aggregator
     (rg6_control joint_states.launch.py, clearpath-custom-joint-states.service)
     keeps the platform/joint_states bus complete for RSP + move_group.

  4. RG6 into the generated MoveIt config (run_rg6_moveit_patch).

  5. Physical properties into the apt descriptions (run_urdf_physics_patch):
     joint dynamics on the arm and the wheels, an inertial on the top plate.
     Numbered last, RUNS FIRST -- it edits what the Clearpath generator reads,
     where step 4 edits what it writes.

  6. This vehicle's loaded wheel radius into the a200 description
     (run_ride_height_patch), so base_footprint -- the ground reference every
     calibrated height is measured against -- sits where the squashed tyres put
     it. Same window as step 5.

Every edit is surgical, idempotent, with a .bak backup and an atomic write.
If a file or a key is missing, that change is skipped (with a warning).

Note: 'update_rate' (125) and 'io_and_status_controller' are NOT patched here
-> both go through robot.yaml arm-level 'ros_parameters'
(clearpath_common PR #347).
"""

import os
import re
import shutil
import sys

TAG = "clearpath-custom-setup"

#: The remap pair of the arm JSB in clearpath_manipulators/control.launch.py.
#: Deliberately anchored on the SECOND token: 'platform','dynamic_joint_states'
#: sits right next to it and must not be touched.
ARM_JS_RX = re.compile(r"([\'\"])platform\1(\s*,\s*)([\'\"])joint_states\3")
ARM_JS_SUB = r"\1manipulators\1\2\3joint_states\3"

# ---------------------------------------------------------------------------


def log(msg, err=False):
    """Log line (stdout/stderr); captured by journald via SyslogIdentifier."""
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def move_arm_joint_states(label):
    """Remap the arm JSB publisher from platform/ -> manipulators/joint_states.

    clearpath_manipulators/control.launch.py remaps the joint_states output of
    the manipulators ros2_control_node via
        ('joint_states', PathJoinSubstitution(['/', namespace, 'platform', 'joint_states']))
    to /<ns>/platform/joint_states. That makes the arm JSB advertise in the
    platform namespace by mistake. Here the token sequence
    'platform','joint_states' becomes 'manipulators','joint_states' ->
    /<ns>/manipulators/joint_states.

    dynamic_joint_states deliberately stays on platform: the line
    'platform','dynamic_joint_states' is NOT matched (after the comma it says
    'dynamic_joint_states', not 'joint_states'). Applies to the apt stock file
    under /opt/ros/*/share -> idempotent on every boot (survives apt updates).
    A relay (rg6_control joint_states.launch.py) mirrors manipulators/joint_states
    back onto platform/joint_states for RSP/move_group (live TF/MoveIt untouched).
    """
    import glob

    files = glob.glob("/opt/ros/*/share/clearpath_manipulators/launch/control.launch.py")
    rx = ARM_JS_RX
    changed = []
    for path in files:
        try:
            with open(path) as f:
                content = f.read()
        except OSError as e:
            # Skipped, so the patch this file was meant to receive never lands -- and the run still reports
            # success for the files it DID reach.
            log(f"{label}: cannot read {path}, skipping: {e}", err=True)
            continue
        new_content, n = rx.subn(ARM_JS_SUB, content)
        if n == 0:
            continue  # already patched, or the pattern is not (or no longer) present
        backup = path + ".bak"
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError as e:
                # The patch below goes ahead regardless, but without the .bak it cannot be undone.
                log(f"{label}: no backup of {path}: {e}", err=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(new_content)
            os.replace(tmp, path)
            changed.append(f"{os.path.basename(path)} ({n}x)")
        except OSError as e:
            log(f"{label}: cannot write {path}: {e}", err=True)
    if changed:
        log(f"{label}: Arm joint_states -> manipulators in: {', '.join(changed)}")
    else:
        log(f"{label}: already manipulators (or pattern not found) - no change.")
    return bool(changed)


def run_root_tool(label, tool, args=(), *, missing):
    """Call one of the root-owned patch tools the installer placed in /usr/local/bin, and relay its output.

    Deliberately NO call directly out of /home/*: this service runs as root, so code from a user-writable
    workspace would be a privilege escalation (workspace/repo write access -> root on every boot; via ``git pull``
    even the remote repo).  A copy under /usr/local/bin only changes through another installer run, which is an
    explicit admin decision.

    A missing copy is a warning and a ``False``, never an abort: each of the three callers below can say what its
    absence costs, and none of those costs is worth taking the boot down for.

    :param missing: what the caller loses when the tool is not there -- appended to the warning, so the log says
        which capability is gone rather than only which file.  Keyword-only and without a default: a caller that
        cannot name the cost has no business skipping the boot quietly.
    """
    import subprocess

    if not os.path.isfile(tool):
        log(f"{label}: {tool} missing (run the installer again) - {missing}", err=True)
        return False
    try:
        out = subprocess.run([tool, *args], capture_output=True, text=True, timeout=60)
        for line in (out.stdout + out.stderr).splitlines():
            log(f"{label}: {line}")
        if out.returncode != 0:
            log(f"{label}: exit code {out.returncode}.", err=True)
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"{label}: call failed: {e}", err=True)
        return False


def run_sensor_mesh_uri_patch(label):
    """Rewrite the sensor mesh URIs from file:// to package://, so the foxglove_bridge will serve them.

    The tool is a script of this repo (``scripts/sensor_mesh_uri_patch.py``) and carries the whole reasoning --
    what upstream ships, why neither "the URDF builds" nor "Foxglove shows it" settles the question, and what the
    bridge's ``asset_uri_allowlist`` does with a ``file://``.

    It is a script of its own rather than a function here because the husky-offboard container needs the SAME
    patch on its OWN copy of those apt xacros: the robot and the container each generate a URDF, and a difference
    between the two must never be explainable by the fix having run on one side only.  A copy in the image is the
    one thing an fetch of robot.yaml cannot deliver.

    Applies to apt-installed files, so it is re-applied on every boot -- an apt update rolls them back."""
    return run_root_tool(
        label,
        "/usr/local/bin/sensor-mesh-uri-patch",
        missing="sensor meshes stay file:// - the camera model is invisible in Foxglove.",
    )


def run_rg6_moveit_patch(label):
    """Hook the RG6 into the freshly generated MoveIt config.

    The tool comes from the onrobot-rg6 workspace (rg6_moveit_patch: robot.srdf, idempotent).  It does NOT patch
    moveit.yaml - gripper controller and joint_limits come from robot.yaml
    (manipulators.moveit.ros_parameters.move_group); the tool only checks that they arrived and exits with code 1
    if they did not.

    Must run AFTER clearpath-robot-generate and BEFORE clearpath-manipulators - exactly the window of this
    service."""
    return run_root_tool(
        label,
        "/usr/local/bin/rg6-moveit-patch",
        args=("--setup-path", "/etc/clearpath"),
        missing="MoveIt without the gripper (is onrobot-rg6 cloned and built?).",
    )


def run_urdf_physics_patch(label):
    """Put physical properties into the apt descriptions, before the generator expands them.

    The tool is a script of this repo (``scripts/urdf_physics_patch.py``), unlike the SRDF patcher, which comes
    from the onrobot-rg6 workspace: every target here is an arm, wheel or platform property, and none of them is a
    gripper part.

    It and ``rg6_moveit_patch`` differ in WHEN they have to run, and it is worth being precise about it.
    ``rg6_moveit_patch`` edits the flat robot.srdf the generator PRODUCES, so it runs after
    clearpath-robot-generate.  This one edits the package xacros the generator CONSUMES -- ur_description's zero
    joint dynamics, the wheel joints without any, the top plate without an inertial -- so it has to run before.
    Both windows are inside this service; the ordering here is the whole of it.

    Every target is still waiting for a measurement (R47), so today the tool reports and changes nothing.  It is
    called regardless: the alternative is a call site that first runs on the day somebody fills in a value."""
    return run_root_tool(
        label,
        "/usr/local/bin/urdf-physics-patch",
        missing="descriptions stay as apt ships them.",
    )


def run_ride_height_patch(label):
    """Put this vehicle's loaded wheel radius into the a200 description, before the generator expands it.

    The tool is a script of this repo (``scripts/ride_height_patch.py``) and carries the measurement.  Same window
    as ``urdf_physics_patch`` -- it edits a package xacro the generator CONSUMES -- but a separate tool on purpose:
    that one is about physical properties a physics engine needs and deliberately holds no measured value, this one
    is geometry and holds one.

    What it moves is ``base_footprint``, the ground reference of the whole workspace.  The alternative that looks
    equivalent -- carrying the same 31 mm as a ``top_plate`` offset in robot.yaml -- is not: it lowers the deck
    against the chassis instead of the vehicle against the ground, and the superstructure then intersects both the
    chassis and the wheels.  Measured on 2026-09-01, move_group answers ``valid=False`` for every state in that
    shape, so nothing plans at all."""
    return run_root_tool(
        label,
        "/usr/local/bin/ride-height-patch",
        missing="base_footprint stays on the NOMINAL wheel radius.",
    )


def selftest():
    """Exercise the remap pattern without touching a file or needing ROS.

    It is string surgery on a file this installer does not own (it comes from apt and is regenerated), so the only
    thing that can be tested off the robot is whether the pattern hits what it must and spares what it must not.

    The mesh URI swap is NOT here: it is its own tool now, with its own tests
    (``tests/test_sensor_mesh_uri_patch.py``), and every other step is a call to a root-owned copy that only
    exists on the robot.
    """
    # The remap pair as clearpath_manipulators writes it.
    src = (
        "            ('joint_states', PathJoinSubstitution(\n"
        "                ['/', namespace, 'platform', 'joint_states'])),\n"
        "            ('dynamic_joint_states', PathJoinSubstitution(\n"
        "                ['/', namespace, 'platform', 'dynamic_joint_states'])),\n"
    )
    out, n = ARM_JS_RX.subn(ARM_JS_SUB, src)
    assert n == 1, f"expected exactly one hit, got {n}"
    assert "'manipulators', 'joint_states'" in out, "arm JSB not remapped"
    assert "'platform', 'dynamic_joint_states'" in out, "dynamic_joint_states was touched"

    # Idempotent: a second run finds nothing left to do.
    assert ARM_JS_RX.subn(ARM_JS_SUB, out)[1] == 0, "not idempotent"

    # Double quotes and loose spacing are the same line to the pattern.
    assert ARM_JS_RX.subn(ARM_JS_SUB, '["platform" ,  "joint_states"]')[1] == 1, "quoting/spacing"

    print("clearpath_custom_setup selftest: OK (arm joint_states remap)")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    log("start.")
    # What this patcher does NOT touch, and where it lives instead.  The
    # numbers of the remaining steps stay as they are, so that references to
    # them (such as "step 3" in the watchdog) keep pointing at the right thing.
    #
    #  * 'update_rate' (125) and 'io_and_status_controller': robot.yaml,
    #    arm-level 'ros_parameters' (clearpath_common PR #347, verified
    #    2026-06).
    #  * The foxglove allowlist: robot.yaml under
    #    platform.extras.ros_parameters.foxglove_bridge -- but
    #    BACKSLASH-FREE ([A-Za-z0-9_] instead of \w, [.] instead of \.). The
    #    generator's ParamWriter serialises lists through Python's repr and
    #    doubles every backslash while doing so; YAML single quotes read it
    #    back literally, and the regex then matches nothing. Without
    #    backslashes the value passes through unchanged. Against std::regex --
    #    the engine of the foxglove_bridge, see utils.hpp isWhitelisted -- both
    #    spellings agree on a corpus of matches and non-matches.
    #  * The occupancy map monitor sensor parameters: robot.yaml under
    #    manipulators.moveit.ros_parameters.move_group -- the generator writes
    #    them into moveit.yaml itself.
    #  * The manipulator analyzers: robot.yaml under
    #    platform.extras.ros_parameters.diagnostic_aggregator -- the generator
    #    flattens the nesting onto the dotted keys ROS expects by itself. The
    #    difference to a patch here: a patch would only bite with the
    #    manipulator-diagnostics service installed (the unit file would be the
    #    switch), and robot.yaml does not know that condition -- without the
    #    node, Cockpit shows the group as STALE instead of letting it vanish.
    # 2) Sensor meshes file:// -> package:// (foxglove_bridge only serves package://)
    run_sensor_mesh_uri_patch("sensor mesh package://")
    # 3) Arm JSB joint_states out of the platform namespace ->
    #    manipulators/joint_states (relay + aggregator via clearpath-custom-joint-states.service).
    move_arm_joint_states("arm joint_states -> manipulators")
    # 5) Physical properties into the apt descriptions (ur_description, clearpath_platform_description).
    #    Runs FIRST of the numbered steps although it is numbered last: it edits what the generator reads, while
    #    step 4 edits what the generator writes.  No lever in robot.yaml -- clearpath_config models no joint
    #    dynamics, and both descriptions come from foreign apt repos.
    run_urdf_physics_patch("urdf physics")
    # 6) This vehicle's LOADED wheel radius into the a200 description, so that base_footprint -- the ground
    #    reference every calibrated height is measured against -- matches the squashed tyres under the UR mass.
    #    Runs in the same window as step 5 and for the same reason: it edits what the generator reads.
    run_ride_height_patch("ride height")
    # 4) RG6 into MoveIt: patch robot.srdf (group 'gripper' + EE)
    #    (onrobot-rg6 tool).  For the SRDF there is no lever in robot.yaml --
    #    clearpath_config does not know the word 'srdf', and the gripper enum
    #    (franka/kinova/robotiq) has no RG6.  The moveit.yaml values live in
    #    robot.yaml; the tool only checks them.
    run_rg6_moveit_patch("rg6 moveit")
    log("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
