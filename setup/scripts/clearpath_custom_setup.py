#!/usr/bin/env python3
"""Custom Clearpath setup: patch generated config files after generation,
before the sub-services read them.

The numbering starts at 2 and is kept stable: whatever moves out of here into
robot.yaml leaves its number behind, so references to a step (the watchdog names
step 3) keep pointing at the same thing.  main() lists what left and where to.

Patches:
  2. Sensor mesh URIs file:// -> package:// (fix_realsense_mesh_uris)

  3. Arm JSB joint_states -> manipulators/joint_states (move_arm_joint_states)
     in /opt/ros/*/share/clearpath_manipulators/launch/control.launch.py.
     Detaches the arm joints from the platform namespace; a relay + aggregator
     (rg6_control joint_states.launch.py, clearpath-custom-joint-states.service)
     keeps the platform/joint_states bus complete for RSP + move_group.

  4. RG6 into the generated MoveIt config (run_rg6_moveit_patch).

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

#: Sensor mesh URI as Clearpath ships it, and what it has to become.
MESH_URI_OLD = "file://$(find realsense2_description)"
MESH_URI_NEW = "package://realsense2_description"

#: The remap pair of the arm JSB in clearpath_manipulators/control.launch.py.
#: Deliberately anchored on the SECOND token: 'platform','dynamic_joint_states'
#: sits right next to it and must not be touched.
ARM_JS_RX = re.compile(r"([\'\"])platform\1(\s*,\s*)([\'\"])joint_states\3")
ARM_JS_SUB = r"\1manipulators\1\2\3joint_states\3"

# ---------------------------------------------------------------------------


def log(msg, err=False):
    """Log line (stdout/stderr); captured by journald via SyslogIdentifier."""
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def fix_realsense_mesh_uris(label):
    """Clearpath's sensor xacros reference meshes as
    'file://$(find realsense2_description)/...'; switch them to
    'package://realsense2_description' here. Applies to apt-installed files
    under /opt/ros/*/share/clearpath_sensors_description -> re-applied
    idempotently on every boot (survives apt updates too).

    DO NOT REMOVE -- this is not a transitional workaround. Upstream never
    fixed the URIs; checked on the a200-0553 on 2026-08-20 by unpacking and
    reading both .deb files:

        2.9.8  (packages.ros.org)               -> file://, all four intel xacros
        2.9.15 (packages.clearpathrobotics.com) -> file://, all four

    Two probes that can NOT settle this, even though they look as if they
    could:
      * 'the URDF builds without error' -- xacro substitutes $(find ...) and
        writes text, it never opens a mesh. Even a completely made-up
        package:// passes with exit 0 and empty stderr.
      * 'the mesh is visible in Foxglove' -- that shows the state AFTER the
        last patcher run. The patch is persistent: it writes into the package
        files, and they stay written until dpkg overwrites them.
    What counts is solely what is inside the .deb.

    Why it matters at all: not the resource_retriever -- that can do file://
    -- but the 'asset_uri_allowlist' of the foxglove_bridge, which starts with
    ^package:// and rejects everything else. Measured via fetchAsset:
    package://realsense2_description/meshes/d435.dae -> status 0, 15782439
    bytes; the same file as file:// -> status 1, 'Failed to retrieve asset'.

    The effect is therefore purely visual (the camera model in the Foxglove 3D
    panel). RViz loads both forms, and the <collision> is a box primitive --
    planning, collision checking and the self filter are not affected.
    Context: R25 in the ROBOTER-TODO archive."""
    import glob

    OLD = MESH_URI_OLD
    NEW = MESH_URI_NEW
    files = glob.glob("/opt/ros/*/share/clearpath_sensors_description/urdf/**/*.urdf.xacro", recursive=True)
    changed = []
    for path in files:
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        if OLD not in content:
            continue
        backup = path + ".bak"
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(content.replace(OLD, NEW))
            os.replace(tmp, path)
            changed.append(os.path.basename(path))
        except OSError as e:
            log(f"{label}: cannot write {path}: {e}", err=True)
    if changed:
        log(f"{label}: package:// set in: {', '.join(sorted(changed))}")
    else:
        log(f"{label}: already package:// (or nothing found) - no change.")
    return bool(changed)


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
        except OSError:
            continue
        new_content, n = rx.subn(ARM_JS_SUB, content)
        if n == 0:
            continue  # already patched, or the pattern is not (or no longer) present
        backup = path + ".bak"
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
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


def run_rg6_moveit_patch(label):
    """Hook the RG6 into the freshly generated MoveIt config.

    Delegates to the root-owned copy of the self-contained tool from the
    onrobot-rg6 repo (rg6_moveit_patch: robot.srdf, idempotent) that the
    installer copies to /usr/local/bin.  It does NOT patch moveit.yaml -
    gripper controller and joint_limits come from robot.yaml
    (manipulators.moveit.ros_parameters.move_group); the tool only checks that
    they arrived and exits with code 1 if they did not.

    Deliberately NO call directly out of /home/*: this service runs as root -
    code from a user-writable workspace would be a privilege escalation
    (workspace/repo write access -> root on every boot). The copy only changes
    through another installer run (an explicit admin decision).
    Must run AFTER clearpath-robot-generate and BEFORE clearpath-manipulators -
    exactly the window of this service. If the copy is missing (the installer
    never ran with an onrobot-rg6 workspace present), only a warning is
    issued."""
    import subprocess

    tool = "/usr/local/bin/rg6-moveit-patch"
    if not os.path.isfile(tool):
        log(
            f"{label}: {tool} missing (run the installer with an "
            "onrobot-rg6 workspace) - MoveIt without the gripper.",
            err=True,
        )
        return False
    try:
        out = subprocess.run([tool, "--setup-path", "/etc/clearpath"], capture_output=True, text=True, timeout=60)
        for line in (out.stdout + out.stderr).splitlines():
            log(f"{label}: {line}")
        if out.returncode != 0:
            log(f"{label}: exit code {out.returncode}.", err=True)
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"{label}: call failed: {e}", err=True)
        return False


def selftest():
    """Exercise the two patterns without touching a file or needing ROS.

    Both are string surgery on files this installer does not own (they come from
    apt and are regenerated), so the only thing that can be tested off the robot
    is whether the patterns hit what they must and spare what they must not.
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

    # The mesh URI swap, and that it leaves a foreign package alone.
    xacro = f'<mesh filename="{MESH_URI_OLD}/meshes/d435.dae"/>'
    assert (
        xacro.replace(MESH_URI_OLD, MESH_URI_NEW)
        == '<mesh filename="package://realsense2_description/meshes/d435.dae"/>'
    ), "mesh uri"
    other = '<mesh filename="file://$(find rg6_description)/meshes/hand.dae"/>'
    assert other.replace(MESH_URI_OLD, MESH_URI_NEW) == other, "foreign package touched"

    print("clearpath_custom_setup selftest: OK (arm joint_states remap, mesh uri)")
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
    fix_realsense_mesh_uris("sensor mesh package://")
    # 3) Arm JSB joint_states out of the platform namespace ->
    #    manipulators/joint_states (relay + aggregator via clearpath-custom-joint-states.service).
    move_arm_joint_states("arm joint_states -> manipulators")
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
