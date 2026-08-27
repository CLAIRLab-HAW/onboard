#!/usr/bin/env bash
#
# All-in-one installer for the Clearpath a200-0553 custom setup + OnRobot RG6.
#
# Does all of this in one go, in this order ("optional" = it asks first):
#   - robot.yaml: clone the repo and point /etc/clearpath/robot.yaml at it as a
#     SYMLINK (the official Clearpath way). FIRST, because everything this
#     installer deploys is resolved against that checkout. No network dependency
#     in the boot path, reproducible, and a 'git pull' takes effect immediately
#     (clearpath-robot-check md5sums the file every second).
#   - boot service clearpath-custom-setup: patches the generated configs on
#     EVERY boot (realsense mesh uris, arm joint_states bus, rg6 srdf)
#   - udev rules (/etc/udev/rules.d/99-husky.rules), netplan (/etc/netplan/01-netcfg.yaml),
#     disable systemd-networkd (NetworkManager)
#   - sysctl 10-ur-reserved-ports.conf: takes the UR driver ports 50001-50004 out
#     of the ephemeral range, so nothing else can occupy them before the driver
#   - optional: speed up the GRUB boot (hide the menu, GRUB_TIMEOUT=0)
#   - clone + build onrobot-rg6 via git (colcon), plus a root-owned copy of
#     rg6_moveit_patch under /usr/local/bin for the boot service
#   - optional: clearpath-custom-ur-dashboard.service: starts the ur_robot_driver
#     dashboard_client (power_on/brake_release/unlock_protective_stop/restart_safety)
#     at boot
#   - optional: clearpath-custom-ur-state-manager.service: clones + builds
#     ur-state-manager and starts the state manager
#     (prepare/recover/ensure_ready/power_off) at boot
#     (including the extra controller --inactive + ur_controller_mode_manager --
#     part of the same launch, no separate arm-controllers unit)
#   - optional: clearpath-custom-manipulators-watchdog.timer: restarts
#     clearpath-manipulators.service when the arm is powered up LONG after the
#     boot (ros2_control does not retry the HW activation that failed once ->
#     the driver stays dead). It checks for "arm pingable, but
#     robot_program_running does not publish" and restarts ONCE. Installs the
#     SIGINT stop drop-in on clearpath-manipulators.service along with it.
#   - clearpath-custom-joint-states.service: joint_state_aggregator
#     (/a200_0553/joint_states) plus the relays back onto the platform bus
#   - optional: clearpath-custom-octomap-feed.service: throttled depth ->
#     PointCloud2 for MoveIt's occupancy map monitor
#   - optional: clearpath-custom-manipulator-diagnostics.service: UR5 + RG6 as
#     diagnostic_msgs for the Clearpath aggregator (Cockpit, diagnostics_agg)
#   - rtde_input_recipe_no_tool.txt into the home directory: without it the UR
#     driver does not start alongside the OnRobot URCap
#   - clearpath-custom-rg6-grip-bridge.service: commands the RG6 over XML-RPC to
#     the OnRobot URCap and publishes the finger joint plus the gripper state
#   - optional: the cockpit-ros2-diagnostics fork with the manipulator panel to
#     /usr/local/share/cockpit (shadows the apt plugin under /usr/share)
#
# Note on robot.yaml: the repo is the single source of truth,
#   /etc/clearpath/robot.yaml is a SYMLINK onto it. So maintain changes in the
#   repo clone - they take effect immediately (clearpath-robot-check restarts
#   the stack when the content changes).
#
# Invocation (sudo is acquired when needed):
#   bash install-clearpath-custom-setup.sh         # interactive (asks when
#                                                    changes are already
#                                                    active or differ)
#   bash install-clearpath-custom-setup.sh -y      # answer every question with "yes"
#   bash install-clearpath-custom-setup.sh --verify # ONLY check: hashes the
#                                                     rolled-out copies against
#                                                     the checkout, changes
#                                                     nothing, needs no root
#
# The four repo URLs (onrobot-rg6, ur-state-manager, husky-custom-setup,
# cockpit-ros2-diagnostics) sit in the configuration block below; a fork
# changes them there.
#
# Idempotent: runnable any number of times, and it installs no package.
#
# NOT here: the UR kinematics calibration.  It is scripts/ur-calibrate.sh --
# see the section further down that says why.

set -euo pipefail

# ---- configuration ---------------------------------------------------------
RG6_REPO_URL="https://github.com/CLAIRLab-HAW/onrobot-rg6.git"
USM_REPO_URL="https://github.com/CLAIRLab-HAW/ur-state-manager.git"
# UR control box + manipulators namespace: ONE source for dashboard, watchdog
# and calibration (the section variables below derive from these).
ARM_ROBOT_IP="192.168.131.40"
MANIP_NS="/a200_0553/manipulators"
BIN_DIR="/usr/local/bin"
PY_PATH="${BIN_DIR}/clearpath-custom-setup.py"
UNIT_NAME="clearpath-custom-setup.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"

# RG6 gripper bridge: commands the gripper over XML-RPC to the OnRobot URCap
# (block further down).  The NAMES sit up here because the diagnostics unit
# needs them in its After= and is written further up -- under 'set -u' a later
# definition would be an abort, not an empty field.
RG6_BRIDGE_BIN="${BIN_DIR}/rg6-grip-bridge"
RG6_BRIDGE_WRAPPER="${BIN_DIR}/rg6-grip-bridge-wrapper"
RG6_BRIDGE_UNIT="clearpath-custom-rg6-grip-bridge.service"
RG6_BRIDGE_UNIT_PATH="/etc/systemd/system/${RG6_BRIDGE_UNIT}"
# Root-owned copy of the rg6_moveit_patch tool (see the copy step after the
# rg6 build). The boot service clearpath-custom-setup (root) calls ONLY this
# copy - never the user-writable workspace directly.
RG6_MOVEIT_PATCH_BIN="${BIN_DIR}/rg6-moveit-patch"

# Octomap feed (step 2 of the HRL obstacle architecture): throttled
# depth->PointCloud2 source for MoveIt's occupancy map monitor, so that
# move_group also avoids UNTRACKED obstacles (the dense voxel layer; the
# object-based boxes from the workstation stay for task objects + twin).
# The canonical source is in the repo (scripts/octomap_feed.py, SSOT like
# robot.yaml); a root-owned copy sits under /usr/local/bin, started by the boot
# service.  repo_file resolves the source (checkout before GitHub main, see
# there) -- which is why no URL stands here.
OCTO_FEED_BIN="${BIN_DIR}/octomap-feed"
OCTO_WRAPPER="${BIN_DIR}/octomap-feed.sh"
OCTO_UNIT="clearpath-custom-octomap-feed.service"
OCTO_UNIT_PATH="/etc/systemd/system/${OCTO_UNIT}"

# Manipulator diagnostics: translates UR mode/safety/external control and the
# RG6 state into diagnostic_msgs and publishes them on the /diagnostics topic
# the Clearpath diagnostic_aggregator subscribes to. Only with this does the
# manipulator appear in diagnostics_agg at all -- so in Cockpit,
# rqt_robot_monitor and the diagnostics capture. The matching analyzer block
# comes from robot.yaml.
# The source resolves through repo_file as for the octomap feed (checkout
# before GitHub main).
MD_BIN="${BIN_DIR}/manipulator-diagnostics"
MD_WRAPPER="${BIN_DIR}/manipulator-diagnostics.sh"
MD_UNIT="clearpath-custom-manipulator-diagnostics.service"
MD_UNIT_PATH="/etc/systemd/system/${MD_UNIT}"

# Cockpit plugin (fork of clearpathrobotics/cockpit-ros2-diagnostics with the
# manipulator panel). Cockpit searches packages in this order:
# ~/.local/share/cockpit, /etc/cockpit, /usr/local/share/cockpit,
# /usr/share/cockpit -- so the fork under /usr/local shadows the apt package
# under /usr/share without touching it. Uninstalling = delete the directory,
# then the original is active again (no apt needed).
# The directory name MUST be 'ros2-diagnostics' (package.json "name"),
# otherwise it does not shadow but appears as a second menu entry.
CKPT_REPO_URL="https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics.git"
CKPT_PKG_DIR="/usr/local/share/cockpit/ros2-diagnostics"

# UR dashboard_client: Clearpath does NOT start it in the headless setup, but
# it provides power_on/brake_release/unlock_protective_stop/restart_safety/get_*_mode.
# No build needed (comes from ros-jazzy-ur-robot-driver). robot_ip = UR control box.
UR_DASH_WRAPPER="${BIN_DIR}/ur-dashboard.sh"
UR_DASH_UNIT="clearpath-custom-ur-dashboard.service"
UR_DASH_UNIT_PATH="/etc/systemd/system/${UR_DASH_UNIT}"
UR_DASH_NS="${MANIP_NS}"
UR_DASH_ROBOT_IP="${ARM_ROBOT_IP}"

# ur-state-manager: prepare/recover/ensure_ready/power_off services for the arm.
# Cloned + built (like onrobot-rg6) and started by a boot service. Needs the
# dashboard_client (clearpath-custom-ur-dashboard.service) -> starts the launch with start_dashboard_client:=false.
USM_WRAPPER="${BIN_DIR}/ur-state-manager.sh"
USM_UNIT="clearpath-custom-ur-state-manager.service"
USM_UNIT_PATH="/etc/systemd/system/${USM_UNIT}"

# joint-states: robot-wide joint_state_aggregator (/a200_0553/joint_states)
# plus relays of the clean arm/gripper source topics back onto the
# platform/joint_states bus (for RSP + move_group). Uses the onrobot-rg6
# workspace (rg6_control joint_states.launch.py), no build of its own.
JS_WRAPPER="${BIN_DIR}/joint-states.sh"
JS_UNIT="clearpath-custom-joint-states.service"
JS_UNIT_PATH="/etc/systemd/system/${JS_UNIT}"

# manipulators watchdog: covers TWO gaps that are NOT solvable at the ROS level.
#  (a) If the UR is powered up LONG AFTER the boot, the one-shot ros2_control HW
#      activation of the ur_robot_driver fails (the arm was unpowered) - and
#      ros2_control does NOT retry it. Result: JSC silent, arm stays "Stopped".
#  (b) A clearpath-robot.service restart with the arm already powered: the old
#      external control instance holds the reverse socket, the new HW activation
#      fails -> JSC silent -> the arm goes flat in RViz. (robot_program_running
#      alone is NOT a health signal: it is controller side and stays 'true' with
#      a dead PC-side motion link.)
# The health signal is therefore the joint_state_broadcaster stream
# (.../manipulators/joint_states). This timer detects "arm pingable, but JSC
# silent" and restarts clearpath-manipulators.service ONCE (with a cooldown
# against loops). In addition a SIGINT stop drop-in on
# clearpath-manipulators.service pins a graceful ROS shutdown instead of the
# SIGTERM ignore (a 90 s zombie with a socket collision).
WD_WRAPPER="${BIN_DIR}/manipulators-watchdog.sh"
WD_UNIT="clearpath-custom-manipulators-watchdog.service"
WD_UNIT_PATH="/etc/systemd/system/${WD_UNIT}"
WD_TIMER="clearpath-custom-manipulators-watchdog.timer"
WD_TIMER_PATH="/etc/systemd/system/${WD_TIMER}"
WD_ROBOT_IP="${ARM_ROBOT_IP}"
WD_PROGRAM_TOPIC="${MANIP_NS}/io_and_status_controller/robot_program_running"
# SIGINT stop drop-in for clearpath-manipulators.service (a clean driver
# shutdown, see the script comment). The drop-in survives Clearpath package
# updates (it layers over /usr/lib/systemd/system/clearpath-manipulators.service).
WD_MANIP_DROPIN_DIR="/etc/systemd/system/clearpath-manipulators.service.d"
WD_MANIP_DROPIN="${WD_MANIP_DROPIN_DIR}/override.conf"

# robot.yaml: the git repo is the single source of truth. /etc/clearpath/robot.yaml
# is a symlink onto the clone, so a 'git pull' takes effect immediately.
SETUP_REPO_URL="https://github.com/CLAIRLab-HAW/husky-custom-setup.git"
ROBOT_YAML_PATH="/etc/clearpath/robot.yaml"
# ---------------------------------------------------------------------------

# --- arguments -------------------------------------------------------------
#   -y/--yes   answers every question with "yes"
#   --verify   hashes the rolled-out artefacts against the checkout and EXITS.
#              Read only -- hence evaluated BEFORE the root re-exec, so that a
#              quick look does not ask for sudo.
ASSUME_YES=0
DO_VERIFY=0
for _a in "$@"; do
    case "$_a" in
        -y|--yes) ASSUME_YES=1 ;;
        --verify) DO_VERIFY=1 ;;
    esac
done

# Only the roll-out run needs root, --verify does not.
if [ "$DO_VERIFY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "Need root privileges - restarting via sudo ..."
    exec sudo -- bash "$0" "$@"
fi

# confirm "question" -> 0 (yes) / 1 (no).
#   -y            -> always yes
#   no console    -> no (non-interactive, overwrite nothing) -> does NOT hang
#   timeout 60 s  -> no (prevents waiting forever)
# The prompt deliberately goes straight to /dev/tty (visible!), not to stderr.
confirm() {
    local _ans
    [ "$ASSUME_YES" -eq 1 ] && return 0
    # Is /dev/tty really openable? (test the open, not just the permissions)
    if ! { true < /dev/tty; } 2>/dev/null; then
        echo "    (no interactive console ─▶ skipped; force it with -y)"
        return 1
    fi
    printf '%s [y/N] ' "$1" > /dev/tty
    if ! read -r -t 60 _ans < /dev/tty; then
        printf '\n    (no input/timeout ─▶ skipped)\n' > /dev/tty
        return 1
    fi
    case "$_ans" in [jJyY]*) return 0 ;; *) return 1 ;; esac
}

# Rotate timestamped backups ("<file>.bak.<timestamp>"): keep only the KEEP
# newest ones (default 5). Never fatal (empty glob etc.) -> safe under set -e.
prune_backups() {
    local file="$1" keep="${2:-5}"
    ls -1t "${file}".bak.* 2>/dev/null | tail -n "+$((keep + 1))" | xargs -r rm -f -- || true
}

# The real user (for the workspace build), not root:
REAL_USER="${SUDO_USER:-robot}"
USER_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
RG6_WS="${USER_HOME}/onrobot-rg6"
USM_WS="${USER_HOME}/ur-state-manager"
SETUP_WS="${USER_HOME}/husky-custom-setup"   # versioned robot.yaml (symlink target)

# Find a file of THIS repo.  The installer does NOT necessarily run out of the
# checkout -- it is called standalone, and then "$(dirname "$0")" is an
# arbitrary directory and every assumption "the file lies next to me" collapses.
# That is exactly what failed on 2026-08-19: install(1) got source == target and
# aborted with "are the same file", and because set -e applies, the whole run
# died in the middle of the roll-out.
#
# Order: next to the script, then the clone the installer maintains for
# robot.yaml anyway (SETUP_WS, see above), and only after that the network.
# Local BEFORE GitHub, otherwise main silently overwrites a checked-out state --
# that is ROBOTER-TODO archive R6.  Prints the path on stdout; a return != 0 means "not
# found anywhere", and the caller decides whether that is a warning or an abort.
# NOBODY aborts here.
repo_file() {
    local rel="$1" candidate tmp url
    for candidate in "$(dirname "$0")/${rel}" "${SETUP_WS}/${rel}"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    # curl OR wget -- the documented install path is a wget of this one file, so
    # a machine that has wget but no curl is exactly the machine that gets here.
    # Insisting on curl made repo_file fail silently there.
    tmp="$(mktemp)"
    url="https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/${rel}"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 5 --max-time 30 "$url" -o "$tmp" && {
            printf '%s\n' "$tmp"; return 0; }
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=30 --tries=2 -O "$tmp" "$url" && {
            printf '%s\n' "$tmp"; return 0; }
    fi
    rm -f "$tmp"
    return 1
}

# A required file that repo_file cannot produce is fatal, and it has to say so
# HERE rather than leave a unit without an ExecStart behind.  Prints the path.
require_repo_file() {
    local rel="$1" path
    if ! path="$(repo_file "$rel")"; then
        echo "ERROR: ${rel} is required and was found nowhere:" >&2
        echo "       - not next to this script ($(dirname "$0"))" >&2
        echo "       - not in the checkout (${SETUP_WS})" >&2
        echo "       - and not reachable at raw.githubusercontent.com" >&2
        echo "       Clone the repo and run the installer out of it, or restore" >&2
        echo "       network access to github.com." >&2
        exit 1
    fi
    printf '%s\n' "$path"
}

# ---------------------------------------------------------------------------
# --verify: checks whether the rolled-out copies still match what is in the
# checkout.  These artefacts hang off NO git -- under /usr/local/bin sit
# root-owned copies that only change through an installer run.  Whether their
# content matches the source is therefore only known by measuring it; that is
# exactly how the octomap_feed drift across three versions came about
# (ROBOTER-TODO archive R6).
#
# Deliberately LOCAL ONLY: the comparison is against the checkout or
# ${SETUP_WS}, NEVER against GitHub main.  A fallback to the network would
# distort the question -- what is asked is "does what stands here run?", not
# "does what is on main run?".
#
# Read only.  Return 0 = everything matches, 1 = at least one deviation, a
# missing copy or a missing source.
# ---------------------------------------------------------------------------
verify_deployments() {
    local rc=0 entry dst rel src candidate h_dst h_src status
    local -a MANIFEST=(
        "${BIN_DIR}/octomap-feed|scripts/octomap_feed.py"
        "${BIN_DIR}/manipulator-diagnostics|scripts/manipulator_diagnostics.py"
        "${BIN_DIR}/rg6-grip-bridge|scripts/rg6_grip_bridge.py"
        "${BIN_DIR}/rg6_finger_kinematics.json|scripts/rg6_finger_kinematics.json"
        "${USER_HOME}/rtde_input_recipe_no_tool.txt|rtde_input_recipe_no_tool.txt"
    )
    echo "=== --verify: rolled-out copies against the checkout ==="
    for entry in "${MANIFEST[@]}"; do
        dst="${entry%%|*}"
        rel="${entry##*|}"
        src=""
        for candidate in "$(dirname "$0")/${rel}" "${SETUP_WS}/${rel}"; do
            [ -f "$candidate" ] && { src="$candidate"; break; }
        done
        if [ ! -f "$dst" ]; then
            status="NOT-DEPLOYED"; rc=1
        elif [ -z "$src" ]; then
            status="SOURCE-MISSING"; rc=1
        else
            h_dst="$(sha256sum "$dst" | cut -d" " -f1)"
            h_src="$(sha256sum "$src" | cut -d" " -f1)"
            if [ "$h_dst" = "$h_src" ]; then status="OK"; else status="DEVIATION"; rc=1; fi
        fi
        printf "  %-16s %-46s ◀─ %s\n" "$status" "$dst" "${src:-${rel} (not found)}"
    done

    # rg6-moveit-patch comes from the onrobot-rg6 workspace, not from this repo
    # -- its own candidate list, otherwise the manifest run would never find it.
    src=""
    for candidate in "${RG6_WS}/install/rg6_control/lib/rg6_control/rg6_moveit_patch" \
                     "${RG6_WS}/src/rg6_control/scripts/rg6_moveit_patch"; do
        [ -f "$candidate" ] && { src="$candidate"; break; }
    done
    if [ ! -f "$RG6_MOVEIT_PATCH_BIN" ]; then
        status="NOT-DEPLOYED"; rc=1
    elif [ -z "$src" ]; then
        # Not an error: the workspace does not have to be built on the robot.
        status="SOURCE-MISSING"
    elif [ "$(sha256sum "$RG6_MOVEIT_PATCH_BIN" | cut -d" " -f1)" \
         = "$(sha256sum "$src" | cut -d" " -f1)" ]; then
        status="OK"
    else
        status="DEVIATION"; rc=1
    fi
    printf "  %-16s %-46s ◀─ %s\n" "$status" "$RG6_MOVEIT_PATCH_BIN" \
           "${src:-onrobot-rg6 workspace (not built)}"

    if [ "$rc" -eq 0 ]; then
        echo "  ─▶ everything matches."
    else
        echo "  ─▶ DEVIATIONS. An installer run brings the copies to the checkout state."
    fi
    return "$rc"
}

if [ "$DO_VERIFY" -eq 1 ]; then
    verify_deployments && exit 0 || exit 1
fi

CKPT_WS="${USER_HOME}/cockpit-ros2-diagnostics"

# --- robot.yaml: clone the repo (SSOT) + symlink -- FIRST -------------------
# FIRST, because repo_file resolves against ${SETUP_WS}: the patcher, the
# watchdog and the four deployed scripts all come out of this checkout.  Ahead
# of it, only "next to the script" or the network can answer, and a wget of the
# single installer file has no "next to the script".
# Clearpath intends robot.yaml to be kept under version control and placed at
# /etc/clearpath/robot.yaml as a SYMLINK (the customization package concept). No
# network dependency in the boot path, reproducible, and a 'git pull' takes effect
# IMMEDIATELY instead of only on the next boot -- clearpath-robot-check md5sums
# /etc/clearpath/robot.yaml every second and restarts the stack on a change
# (md5sum follows the symlink).
echo ">>> robot.yaml: repo clone + symlink (${SETUP_WS} ─▶ ${ROBOT_YAML_PATH})"
if [ -d "${SETUP_WS}/.git" ]; then
    sudo -u "$REAL_USER" git -C "$SETUP_WS" pull --ff-only || echo "    WARN: git pull failed, using the existing state"
else
    sudo -u "$REAL_USER" git clone "$SETUP_REPO_URL" "$SETUP_WS" || echo "    WARN: git clone failed"
fi
if [ -f "${SETUP_WS}/robot.yaml" ]; then
    if [ -L "$ROBOT_YAML_PATH" ] && [ "$(readlink -f "$ROBOT_YAML_PATH")" = "$(readlink -f "${SETUP_WS}/robot.yaml")" ]; then
        echo "    symlink already correct - no change."
    else
        # Back up an existing REAL file before the symlink replaces it.
        if [ -f "$ROBOT_YAML_PATH" ] && [ ! -L "$ROBOT_YAML_PATH" ]; then
            if ! cmp -s "$ROBOT_YAML_PATH" "${SETUP_WS}/robot.yaml"; then
                echo "    ATTENTION: the existing ${ROBOT_YAML_PATH} differs from the repo state!"
                confirm "    Replace it with the symlink anyway (a backup is created)?" || {
                    echo "    robot.yaml: skipped (symlink NOT set)."; SKIP_SYMLINK=1; }
            fi
            [ "${SKIP_SYMLINK:-0}" = "1" ] || cp -a "$ROBOT_YAML_PATH" "${ROBOT_YAML_PATH}.pre-symlink.$(date +%Y%m%d%H%M%S)"
        fi
        if [ "${SKIP_SYMLINK:-0}" != "1" ]; then
            install -d -m 0755 "$(dirname "$ROBOT_YAML_PATH")"
            ln -sfn "${SETUP_WS}/robot.yaml" "$ROBOT_YAML_PATH"
            echo "    symlink set: ${ROBOT_YAML_PATH} ─▶ ${SETUP_WS}/robot.yaml"
        fi
    fi
else
    echo "    WARN: ${SETUP_WS}/robot.yaml missing - symlink NOT set, the existing file stays."
fi

if [ "$RG6_REPO_URL" = "REPLACE_WITH_GIT_URL" ]; then
    echo "ERROR: set RG6_REPO_URL at the top of this script to the git URL of onrobot-rg6."
    exit 1
fi

DO_BOOT=1
if systemctl list-unit-files | grep -q "^${UNIT_NAME}" && [ -f "$PY_PATH" ]; then
    confirm ">>> clearpath-custom-setup is already installed. Update?" || DO_BOOT=0
fi
if [ "$DO_BOOT" -eq 1 ]; then
echo ">>> Installing ${PY_PATH}"
install -d -m 0755 "$BIN_DIR"
cat > "$PY_PATH" <<'PY_EOF'
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
    OLD = "file://$(find realsense2_description)"
    NEW = "package://realsense2_description"
    files = glob.glob(
        "/opt/ros/*/share/clearpath_sensors_description/urdf/**/*.urdf.xacro",
        recursive=True)
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
    files = glob.glob(
        "/opt/ros/*/share/clearpath_manipulators/launch/control.launch.py")
    rx = re.compile(r"(['\"])platform\1(\s*,\s*)(['\"])joint_states\3")
    changed = []
    for path in files:
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        new_content, n = rx.subn(r"\1manipulators\1\2\3joint_states\3", content)
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
        log(f"{label}: {tool} missing (run the installer with an "
            "onrobot-rg6 workspace) - MoveIt without the gripper.", err=True)
        return False
    try:
        out = subprocess.run(
            [tool, "--setup-path", "/etc/clearpath"],
            capture_output=True, text=True, timeout=60)
        for line in (out.stdout + out.stderr).splitlines():
            log(f"{label}: {line}")
        if out.returncode != 0:
            log(f"{label}: exit code {out.returncode}.", err=True)
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"{label}: call failed: {e}", err=True)
        return False


def main():
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
PY_EOF
chmod 0755 "$PY_PATH"

echo ">>> Installing ${UNIT_PATH}"
cat > "$UNIT_PATH" <<'UNIT_EOF'
[Unit]
Description=Custom Clearpath setup: patch generated configs before the sub-services start
# AFTER the generation: control.yaml and foxglove_bridge.yaml are created in
# clearpath-robot.service ExecStartPre (/usr/sbin/clearpath-robot-generate).
After=clearpath-robot.service
Wants=clearpath-robot.service
# Restart along: clearpath-robot.service regenerates the configs in
# ExecStartPre (clearpath-robot-generate) -> the patches get overwritten.
# PartOf makes this service run again on EVERY restart of
# clearpath-robot.service (not only at boot) and patch the configs anew.
# Propagates stop AND restart.
PartOf=clearpath-robot.service
# BEFORE the consumers of the patched files:
#   - clearpath-platform.service starts the foxglove_bridge, which serves the
#     patched sensor meshes (its asset_uri_allowlist comes from robot.yaml and
#     needs no ordering).
#   - clearpath-manipulators.service reads control.launch.py -> the arm JSB
#     joint_states patch (move_arm_joint_states) MUST take effect
#     before that.
Before=clearpath-platform.service clearpath-manipulators.service

[Service]
Type=oneshot
RemainAfterExit=yes
# A clean journal identity:  journalctl -t clearpath-custom-setup -b
SyslogIdentifier=clearpath-custom-setup
StandardOutput=journal
StandardError=journal
ExecStart=/usr/local/bin/clearpath-custom-setup.py

[Install]
WantedBy=multi-user.target
UNIT_EOF
chmod 0644 "$UNIT_PATH"
else
    echo ">>> clearpath-custom-setup: skipped (the existing installation stays)."
fi

# --- udev rules (managed block) --------------------------------------------
UDEV_FILE="/etc/udev/rules.d/99-husky.rules"
UDEV_BEGIN="# >>> clearpath-custom-setup (managed) >>>"
UDEV_END="# <<< clearpath-custom-setup (managed) <<<"

# Build the desired managed block (including markers) in a temp file
udev_block="$(mktemp)"
cat > "$udev_block" <<'UDEV_EOF'
# >>> clearpath-custom-setup (managed) >>>
# Custom rule for CH340/CH341 Serial-to-USB adapter
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="clearpath/prolific clearpath/prolific_$attr{devpath}", MODE="0666"

# Custom rule for FTDI Serial-to-USB adapter (Platform)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A994H1DB", SYMLINK+="clearpath/prolific clearpath/prolific_$attr{devpath}", MODE="0666"

# Custom rule for FTDI Serial-to-USB adapter (UM7)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A908RWEO", SYMLINK+="clearpath/um7", MODE="0666"

# Joystick mapping to prevent adding too many devices
KERNEL=="js*", SUBSYSTEM=="input", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0719", SYMLINK+="input/js0", MODE="0666"
# <<< clearpath-custom-setup (managed) <<<
UDEV_EOF

DO_UDEV=1
if [ -f "$UDEV_FILE" ] && grep -qF "$UDEV_BEGIN" "$UDEV_FILE"; then
    existing_udev="$(mktemp)"
    awk -v b="$UDEV_BEGIN" -v e="$UDEV_END" '$0==b{p=1} p{print} $0==e{p=0}' \
        "$UDEV_FILE" > "$existing_udev"
    if cmp -s "$existing_udev" "$udev_block"; then
        confirm ">>> The udev rules are already active and identical. Write them anyway?" || DO_UDEV=0
    else
        confirm ">>> The udev rules (managed block) differ. Overwrite?" || DO_UDEV=0
    fi
    rm -f "$existing_udev"
fi

if [ "$DO_UDEV" -eq 1 ]; then
    echo ">>> Writing udev rules to ${UDEV_FILE}"
    install -d -m 0755 /etc/udev/rules.d
    touch "$UDEV_FILE"
    tmp_udev="$(mktemp)"
    awk -v b="$UDEV_BEGIN" -v e="$UDEV_END" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ' "$UDEV_FILE" > "$tmp_udev"
    cat "$udev_block" >> "$tmp_udev"
    install -m 0644 "$tmp_udev" "$UDEV_FILE"
    rm -f "$tmp_udev"
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=tty
    echo "    udev rules set and reloaded."
else
    echo ">>> udev rules: skipped."
fi
rm -f "$udev_block"

# --- protect the UR driver ports from ephemeral allocation ------------------
# ur_client_library binds FIXED ports: 50001 reverse, 50002 script sender,
# 50003 trajectory, 50004 script command. All four lie inside the kernel's
# ephemeral port range (net.ipv4.ip_local_port_range = 32768-60999) -> any other
# process can be assigned one of them for an OUTGOING connection before the arm
# driver binds it. This happened for real on 2026-07-29: the
# image_processing_container (clearpath-platform) took 50004 as the source port
# for a loopback connection to teleop_node -> the driver failed with "Failed to
# bind socket for port 50004. Reason: Address already in use" and hung in a
# retry loop; the controller spawners gave up after 5 attempts -> an arm without
# controllers. Restarting the driver did NOT help (the foreign connection stayed
# alive) - only a restart of clearpath-platform freed the port. Reserving takes
# the ports out of the automatic allocation; an explicit bind() by the driver
# stays allowed. Purely additive, idempotent.
SYSCTL_UR_PORTS="/etc/sysctl.d/10-ur-reserved-ports.conf"
echo ">>> Writing ${SYSCTL_UR_PORTS} (reserving UR ports 50001-50004)"
install -d -m 0755 /etc/sysctl.d
cat > "$SYSCTL_UR_PORTS" <<'SYSCTL_EOF'
# Take the UR driver ports (ur_client_library) out of the ephemeral allocation.
# Without this, any process can occupy 50001-50004 as a source port and the
# ur_robot_driver fails to bind ("Address already in use").
net.ipv4.ip_local_reserved_ports = 50001-50004
SYSCTL_EOF
chmod 0644 "$SYSCTL_UR_PORTS"
if sysctl -p "$SYSCTL_UR_PORTS" >/dev/null 2>&1; then
    echo "    active: $(cat /proc/sys/net/ipv4/ip_local_reserved_ports)"
else
    echo "    WARN: sysctl -p failed - it takes effect on the next boot at the latest."
fi

# --- netplan ---------------------------------------------------------------
NETPLAN_FILE="/etc/netplan/01-netcfg.yaml"
echo ">>> Writing netplan ${NETPLAN_FILE}"
install -d -m 0755 /etc/netplan
tmp_np="$(mktemp)"
cat > "$tmp_np" <<'NETPLAN_EOF'
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enp6s0:
      optional: true
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.131.10/24
      link-local: [ ]
NETPLAN_EOF
DO_NETPLAN=1
if [ -f "$NETPLAN_FILE" ] && cmp -s "$tmp_np" "$NETPLAN_FILE"; then
    echo "    netplan already up to date - no change."
    DO_NETPLAN=0
elif [ -f "$NETPLAN_FILE" ]; then
    confirm ">>> netplan ${NETPLAN_FILE} differs. Overwrite (a backup is created)?" || DO_NETPLAN=0
fi
if [ "$DO_NETPLAN" -eq 1 ]; then
    if [ -f "$NETPLAN_FILE" ]; then
        cp -a "$NETPLAN_FILE" "${NETPLAN_FILE}.bak.$(date +%Y%m%d%H%M%S)"
        prune_backups "$NETPLAN_FILE"
    fi
    install -m 0600 "$tmp_np" "$NETPLAN_FILE"
    command -v netplan >/dev/null 2>&1 && { netplan generate || echo "    WARN: netplan generate problem"; }
    echo "    netplan written (mode 0600). 'sudo netplan apply' is NOT automatic."
else
    echo "    netplan: skipped."
fi
rm -f "$tmp_np"

# --- disable systemd-networkd ----------------------------------------------
# Only ask when networkd is active/enabled at all.
networkd_on=0
systemctl is-enabled systemd-networkd.service >/dev/null 2>&1 && networkd_on=1
systemctl is-active  systemd-networkd.service >/dev/null 2>&1 && networkd_on=1
DO_NETWORKD=1
if [ "$networkd_on" -eq 0 ]; then
    echo ">>> systemd-networkd is already inactive - no change."
    DO_NETWORKD=0
else
    confirm ">>> Disable systemd-networkd (in favour of NetworkManager)?" || DO_NETWORKD=0
fi
if [ "$DO_NETWORKD" -eq 1 ]; then
    echo ">>> Disabling systemd-networkd in favour of NetworkManager"
    if systemctl list-unit-files | grep -q '^NetworkManager\.service'; then
        systemctl enable NetworkManager.service 2>/dev/null || true
    fi
    for u in systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service; do
        if systemctl list-unit-files | grep -q "^${u}"; then
            systemctl disable "$u" 2>/dev/null || true
            echo "    disabled: $u"
        fi
    done
else
    echo ">>> systemd-networkd: skipped."
fi

# --- GRUB: fast boot (hide the menu, boot the 1st option directly) ---------
# Optional and OFF by default: a hidden menu makes recovery harder (it still
# comes up by holding SHIFT/ESC during boot). GRUB_TIMEOUT_STYLE=hidden +
# GRUB_TIMEOUT=0 => immediate boot of the default option.
GRUB_FILE="/etc/default/grub"
if [ ! -f "$GRUB_FILE" ]; then
    echo ">>> GRUB: ${GRUB_FILE} not present - skipped."
elif grep -qE '^GRUB_TIMEOUT_STYLE=hidden$' "$GRUB_FILE" && grep -qE '^GRUB_TIMEOUT=0$' "$GRUB_FILE"; then
    echo ">>> GRUB: already set to fast boot - no change."
elif confirm ">>> Speed up the GRUB boot (GRUB_TIMEOUT_STYLE=hidden, GRUB_TIMEOUT=0)?"; then
    cp -a "$GRUB_FILE" "${GRUB_FILE}.bak.$(date +%Y%m%d%H%M%S)"
    prune_backups "$GRUB_FILE"
    # Set GRUB_TIMEOUT_STYLE (replace an existing/commented line, else append)
    if grep -qE '^[#[:space:]]*GRUB_TIMEOUT_STYLE=' "$GRUB_FILE"; then
        sed -i -E 's|^[#[:space:]]*GRUB_TIMEOUT_STYLE=.*|GRUB_TIMEOUT_STYLE=hidden|' "$GRUB_FILE"
    else
        printf 'GRUB_TIMEOUT_STYLE=hidden\n' >> "$GRUB_FILE"
    fi
    # GRUB_TIMEOUT=0 (direct boot); does NOT match GRUB_TIMEOUT_STYLE=
    if grep -qE '^[#[:space:]]*GRUB_TIMEOUT=' "$GRUB_FILE"; then
        sed -i -E 's|^[#[:space:]]*GRUB_TIMEOUT=.*|GRUB_TIMEOUT=0|' "$GRUB_FILE"
    else
        printf 'GRUB_TIMEOUT=0\n' >> "$GRUB_FILE"
    fi
    echo "    ${GRUB_FILE} patched (backup created). Updating GRUB..."
    if command -v update-grub >/dev/null 2>&1; then
        update-grub || echo "    WARN: update-grub failed"
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        grub-mkconfig -o /boot/grub/grub.cfg || echo "    WARN: grub-mkconfig failed"
    else
        echo "    WARN: neither update-grub nor grub-mkconfig found - please run it by hand."
    fi
    echo "    GRUB: fast boot active (the menu is still reachable by holding SHIFT/ESC)."
else
    echo ">>> GRUB: skipped (boot menu unchanged)."
fi

# --- UR kinematics calibration: NOT here ------------------------------------
# It is scripts/ur-calibrate.sh, run deliberately and on its own.  It installs
# packages (the UR stack has to match the ur_client_library ABI) on a robot
# whose UR stack is pinned, and it needs a powered arm -- a measurement
# procedure, not an installation step.  Inside the installer, `-y` answered
# that apt question with "yes" without anyone seeing it.  Since it left, this
# installer installs no package at all: it writes files and units.

# --- clone + build onrobot-rg6 (as the real user, not root) ----------------
DO_RG6=1
if [ -d "${RG6_WS}/.git" ]; then
    confirm ">>> onrobot-rg6 exists in ${RG6_WS}. git pull + rebuild?" || DO_RG6=0
fi
if [ "$DO_RG6" -eq 1 ]; then
    echo ">>> onrobot-rg6 to ${RG6_WS} (user ${REAL_USER})"
    if [ -d "${RG6_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$RG6_WS" pull --ff-only || echo "    WARN: git pull failed, using the existing state"
    else
        sudo -u "$REAL_USER" git clone "$RG6_REPO_URL" "$RG6_WS"
    fi
    echo ">>> Building the workspace (colcon)"
    # rg6_description = gripper model + meshes + clearpath_extras (the glue);
    # rg6_control = simulation gripper, joint_state helper nodes, rg6_moveit_patch.
    #
    # rg6_description carries the gripper model in the URDF, rg6_moveit_patch
    # the SRDF adjustment, and clearpath-custom-joint-states starts the relay out
    # of rg6_control.  The gripper itself is driven by rg6_grip_bridge, not by a
    # node from this workspace.
    #
    # These two are the whole workspace -- onrobot-rg6 ships no interface
    # package.  The bridge publishes its state as flat JSON on rg6/bridge_state,
    # so a reader needs std_msgs and nothing else.  Cross-checked on the robot on
    # 2026-08-24: <ns>/rg6/state does not exist, only bridge_state.
    sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
        "source /etc/clearpath/setup.bash && cd '$RG6_WS' && colcon build --packages-select rg6_description rg6_control" \
        || echo "    WARN: colcon build failed - without rg6_description the gripper is missing from the URDF, without rg6_control the joint-states relay."
else
    echo ">>> onrobot-rg6: skipped (the existing state stays)."
fi

# --- install rg6_moveit_patch as a root-owned copy --------------------------
# The boot service clearpath-custom-setup runs as root and hooks the RG6 into
# the MoveIt config. The tool for that comes from the user workspace - running
# it as root DIRECTLY from there would be a privilege escalation (whoever can
# write into the workspace would get root on every boot; via git pull even the
# remote repo). Hence a root-owned copy here: it only changes through another
# installer run, not through changes in the workspace.
RG6_PATCH_SRC=""
for cand in "${RG6_WS}/install/rg6_control/lib/rg6_control/rg6_moveit_patch" \
            "${RG6_WS}/src/rg6_control/scripts/rg6_moveit_patch"; do
    [ -f "$cand" ] && { RG6_PATCH_SRC="$cand"; break; }
done
if [ -n "$RG6_PATCH_SRC" ]; then
    echo ">>> Installing ${RG6_MOVEIT_PATCH_BIN} (copy of ${RG6_PATCH_SRC})"
    install -m 0755 -o root -g root "$RG6_PATCH_SRC" "$RG6_MOVEIT_PATCH_BIN"
elif [ -f "$RG6_MOVEIT_PATCH_BIN" ]; then
    echo ">>> rg6_moveit_patch: workspace tool not found - the existing copy ${RG6_MOVEIT_PATCH_BIN} stays."
else
    echo "    WARN: rg6_moveit_patch not found (is onrobot-rg6 cloned/built?) - the RG6 MoveIt patch is inactive at boot until the installer runs again with the workspace present."
fi

# --- UR dashboard_client as a boot service (optional) ----------------------
# Provides the dashboard services (power_on/brake_release/unlock_protective_stop/
# restart_safety/get_robot_mode/get_safety_mode). Its own service, no build:
# 'ros2 run ur_robot_driver dashboard_client' connects to <ip>:29999.
# __node:=dashboard_client is pinned -> the services land deterministically under
# ${UR_DASH_NS}/dashboard_client/* (matching the ur_state_manager default).
DO_DASH=1
if [ -f "$UR_DASH_UNIT_PATH" ]; then
    confirm ">>> ${UR_DASH_UNIT} is already installed. Update?" || DO_DASH=0
else
    confirm ">>> Install the UR dashboard_client as a boot service (power_on/brake_release/unlock/restart_safety)?" || DO_DASH=0
fi
if [ "$DO_DASH" -eq 1 ]; then
    echo ">>> Installing ${UR_DASH_WRAPPER} + ${UR_DASH_UNIT}"
    cat > "$UR_DASH_WRAPPER" <<EOF
#!/usr/bin/env bash
# Starts the ur_robot_driver dashboard_client in the manipulators namespace.
# Connects to the UR dashboard server (${UR_DASH_ROBOT_IP}:29999) and creates the
# services ${UR_DASH_NS}/dashboard_client/*.
source /etc/clearpath/setup.bash
exec ros2 run ur_robot_driver dashboard_client --ros-args \\
    -r __ns:=${UR_DASH_NS} \\
    -r __node:=dashboard_client \\
    -p robot_ip:=${UR_DASH_ROBOT_IP}
EOF
    chmod 0755 "$UR_DASH_WRAPPER"

    cat > "$UR_DASH_UNIT_PATH" <<EOF
[Unit]
Description=UR dashboard_client (power_on/brake_release/unlock_protective_stop/restart_safety)
# NO coupling to clearpath-manipulators. The dashboard_client speaks solely
# TCP:29999 with the UR control box and does not need the ROS driver. The
# watchdog restarts clearpath-manipulators and needs the dashboard services
# throughout exactly that recovery (get_robot_mode, get_safety_mode,
# resend_robot_program) - with PartOf it would tear them down itself.
# The ordering against clearpath-robot stays: only after it does
# /etc/clearpath/setup.bash exist.
After=clearpath-robot.service
# PartOf only against clearpath-robot: a stack stop/restart takes it along, a
# pure driver restart (clearpath-manipulators) does not.
PartOf=clearpath-robot.service

[Service]
User=${REAL_USER}
ExecStart=${UR_DASH_WRAPPER}
# dashboard_client exits when the control box (29999) is not ready yet ->
# retry automatically.
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$UR_DASH_UNIT_PATH"
else
    echo ">>> UR dashboard_client: skipped."
fi

# --- clone + build ur-state-manager + boot service (optional) --------------
# prepare/recover/ensure_ready/power_off services for the arm. Like onrobot-rg6:
# clone + build as the real user, then start it via systemd. Needs the
# dashboard_client (clearpath-custom-ur-dashboard.service) -> launch with start_dashboard_client:=false.
DO_USM=1
if [ -d "${USM_WS}/.git" ]; then
    confirm ">>> ur-state-manager exists in ${USM_WS}. git pull + rebuild + update the service?" || DO_USM=0
else
    confirm ">>> Install ur-state-manager (prepare/recover services; clones + builds + boot service)?" || DO_USM=0
fi
if [ "$DO_USM" -eq 1 ]; then
    echo ">>> ur-state-manager to ${USM_WS} (user ${REAL_USER})"
    if [ -d "${USM_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$USM_WS" pull --ff-only || echo "    WARN: git pull failed, using the existing state"
    else
        sudo -u "$REAL_USER" git clone "$USM_REPO_URL" "$USM_WS"
    fi
    echo ">>> Building the workspace (colcon)"
    sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
        "source /etc/clearpath/setup.bash && cd '$USM_WS' && colcon build --packages-select ur_state_manager" \
        || echo "    WARN: colcon build failed - ${USM_UNIT} only runs after a successful build."

    echo ">>> Installing ${USM_WRAPPER} + ${USM_UNIT}"
    cat > "$USM_WRAPPER" <<EOF
#!/usr/bin/env bash
# Starts the ur_state_manager (prepare/recover/ensure_ready/power_off).
# start_dashboard_client:=false -> the dashboard_client runs via clearpath-custom-ur-dashboard.service.
# auto_recover:=false -> the auto_recover watcher is OFF: it would release the
#   brakes and start external control via 'recover' (arm -> RUNNING). After a
#   restart we want ONLY 'driver connected' (the arm stays IDLE, brakes engaged,
#   no automatic brake release or powering). To move it, the operator calls
#   'prepare' by hand. The driver connect happens on its own (JSC); the watchdog
#   is the emergency brake (driver restart only, no brakes/powering).
source /etc/clearpath/setup.bash
source ${USM_WS}/install/setup.bash
exec ros2 launch ur_state_manager ur_state_manager.launch.py start_dashboard_client:=false auto_recover:=false
EOF
    chmod 0755 "$USM_WRAPPER"

    cat > "$USM_UNIT_PATH" <<EOF
[Unit]
Description=UR state manager (prepare/recover/ensure_ready/power_off for the UR5)
# Start after the dashboard_client (which provides the dashboard services). If
# clearpath-custom-ur-dashboard.service is not installed, this After= is a no-op.
After=clearpath-manipulators.service clearpath-custom-ur-dashboard.service
Wants=clearpath-manipulators.service
# Restart along: when clearpath-manipulators (driver/controller_manager)
# restarts, this node must restart too - otherwise the robot_state_helper and the
# adapter point at stale io_and_status_controller topics/services.
# PartOf propagates stop/restart only one hop and only on a DIRECT job on the
# target unit. A stack restart via 'systemctl restart clearpath-robot' starts
# clearpath-manipulators only indirectly -> without PartOf=clearpath-robot this
# service would not restart along. Hence against BOTH roots (robot +
# manipulators); stopping clearpath-robot then stops it too.
PartOf=clearpath-robot.service clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${USM_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$USM_UNIT_PATH"
else
    echo ">>> ur-state-manager: skipped."
fi

# --- arm controllers: no service of their own ------------------------------
# The extra controllers (ft/tcp_pose/speed_scaling active; freedrive/forward/
# passthrough --inactive) and the ur_controller_mode_manager come from
# ur_state_manager.launch.py (argument load_arm_controllers, default true): same
# package, same workspace, same user, identical lifecycle -> no reason for a
# second unit.

# --- manipulators watchdog: driver reconnect on late power-up --------------
# See the variable comment above. Fixes the case "arm unpowered too long ->
# ur_robot_driver failed once -> stays dead", which auto_recover cannot cover by
# construction (wrong level: the watcher needs the dead driver connection for its
# own inputs and cannot restart a process). Timer driven; the wrapper runs as
# root (for systemctl restart), the ROS check as ${REAL_USER} (same ROS graph).
DO_WD=1
if [ -f "$WD_UNIT_PATH" ]; then
    confirm ">>> manipulators-watchdog is already installed. Update?" || DO_WD=0
else
    confirm ">>> Install manipulators-watchdog (driver restart when the arm is powered up late)?" || DO_WD=0
fi
if [ "$DO_WD" -eq 1 ]; then
    echo ">>> Installing ${WD_WRAPPER} + ${WD_UNIT} + ${WD_TIMER}"
    cat > "$WD_WRAPPER" <<'WD_EOF'
#!/usr/bin/env bash
# Watchdog: detects "arm reachable, but the PC-side motion link
# (ur_robot_driver) NOT connected". The health signal is the
# joint_state_broadcaster stream on .../manipulators/joint_states - it publishes
# ONLY when the ros2_control HW interface is activated and reads real arm joints.
# robot_program_running alone is NOT enough as "connected": that is the
# controller-side external control status (via dashboard/RTDE) and stays 'true'
# even when the PC-side motion link is dead - e.g. a stuck reconnect after a
# clearpath-robot.service restart with the arm already powered (the old external
# control instance holds the reverse socket, the new HW activation fails, the JSC
# stays inactive -> topic silent -> the arm goes flat in RViz). It thereby covers
# TWO cases:
#   (a) cold start with a late-powered arm: HW activation failed once (the arm was
#       unpowered), ros2_control does not retry it -> JSC silent.
#   (b) service restart with the arm already powered: the new HW activation fails
#       (socket collision with the old instance) -> JSC silent.
# Recovery: restart the driver (clearpath-manipulators.service) + restart external
# control (resend_robot_program). The arm is NOT powered automatically (no
# power_on/brake_release) - powering is an operator decision (it protects
# maintenance/end of day); with the arm at POWER_OFF no recovery runs (no driver
# loop against an unpowered arm). Protective/safety stops (safety_mode != NORMAL)
# are NOT auto-cleared (they stay manual) - the resend is skipped.
# Invocation: manipulators-watchdog.sh <ROBOT_IP> <TOPIC> <RUN_USER> <RUN_HOME>
#   TOPIC = .../io_and_status_controller/robot_program_running (the namespace is
#   derived from it; dashboard + resend services and the JSC topic sit under the
#   same NS).
set -uo pipefail

ROBOT_IP="${1:?ROBOT_IP missing}"
TOPIC="${2:?TOPIC missing}"
RUN_USER="${3:?RUN_USER missing}"
RUN_HOME="${4:?RUN_HOME missing}"
SERVICE="clearpath-manipulators.service"
DASH_SVC="clearpath-custom-ur-dashboard.service"
COOLDOWN="${WD_COOLDOWN:-180}"          # s: no further recovery for this long after one
JS_TIMEOUT="${WD_JS_TIMEOUT:-25}"      # s: wait for a JSC message (after a manipulators restart the JSC takes up to ~15s -> generous, only >JS_TIMEOUT without a message means the motion link is really dead)
RPR_WAIT="${WD_RPR_WAIT:-15}"           # iterations: confirmation that the JSC streams again after a resend
STATE="/run/manipulators-watchdog.state"
TAG="manipulators-watchdog"
log() { echo "${TAG}: $*"; }

# Derive the namespace from the topic (.../io_and_status_controller/robot_program_running).
NS="${TOPIC%/io_and_status_controller/*}"
DASH_NS="${NS}/dashboard_client"
RESEND_SVC="${NS}/io_and_status_controller/resend_robot_program"
JS_TOPIC="${NS}/joint_states"   # joint_state_broadcaster output; alive only with an active HW interface
PLATFORM_JS_TOPIC="${NS%/manipulators}/platform/joint_states"  # fallback bus (see the health check)
DRY_RUN="${WD_DRY_RUN:-0}"      # 1 = only report what would happen (test)
RPR_TOPIC="${TOPIC}"            # robot_program_running (latched/transient_local!)
RPR_TIMEOUT="${WD_RPR_TIMEOUT:-6}"      # s: wait for the latched value
RESEND_STATE="/run/manipulators-watchdog.resend"
RESEND_COOLDOWN="${WD_RESEND_COOLDOWN:-60}"  # s: do not spam at the timer rate

# Run a ROS command as RUN_USER in the same graph.
ros_cmd() { sudo -u "$RUN_USER" env HOME="$RUN_HOME" bash -lc "source /etc/clearpath/setup.bash && $*"; }

# --- helpers: mode/safety query and trigger calls (all via the dashboard) ---
robot_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_robot_mode' ur_dashboard_msgs/srv/GetRobotMode" 2>&1 | grep -oE 'Robotmode: [A-Z_]+' | head -1; }
safety_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_safety_mode' ur_dashboard_msgs/srv/GetSafetyMode" 2>&1 | grep -oE 'Safetymode: [A-Z_]+' | head -1; }
call_trigger() {  # $1 service path, $2 timeout(s); 0 = success=True
    local svc="$1" t="${2:-12}"
    ros_cmd "timeout ${t} ros2 service call '${svc}' std_srvs/srv/Trigger" 2>&1 | grep -q 'success=True'
}



# --- re-ignite external control (case: RTDE reads, but the motion link is gone) ---
# The JSC already streams as soon as the control box is on - RTDE reading works
# independently of external control. If the arm is powered ONLY AFTER the HW
# activation (typically: the app calls prepare), the external control program sent
# once went nowhere and ros2_control does not repeat it: reading ok, writing dead,
# the arm does not move. The JSC health check does NOT see that - only the
# conjunction "JSC streams AND robot_program_running" is trustworthy. The reaction
# here is deliberately MINIMAL: only resend_robot_program, no driver restart, no
# powering. Gate: only when the operator has already brought the arm to RUNNING and
# no safety fault is pending.
ensure_external_control() {
    ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null \
        | grep -q 'data: true' && return 0
    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN=1 -> external control is not up; would have sent resend_robot_program."
        return 0
    fi
    local rm_now; rm_now="$(robot_mode)"
    if [ "$rm_now" != "Robotmode: RUNNING" ]; then
        return 0   # arm not ready -> do nothing (operator decision)
    fi
    local sm_now; sm_now="$(safety_mode)"
    if [ "$sm_now" != "Safetymode: NORMAL" ]; then
        log "external control is not up, but the safety mode is '${sm_now:-unknown}' -> no resend (manual release needed)."
        return 0
    fi
    local now_r; now_r="$(date +%s)"
    if [ -f "$RESEND_STATE" ]; then
        local last_r; last_r="$(cat "$RESEND_STATE" 2>/dev/null || echo 0)"
        [ -n "$last_r" ] || last_r=0
        if [ "$(( now_r - last_r ))" -lt "$RESEND_COOLDOWN" ]; then
            return 0
        fi
    fi
    echo "$now_r" > "$RESEND_STATE"
    log "the arm is RUNNING and the JSC streams, but external control is not running (robot_program_running != true) -> resend_robot_program. NO driver restart, no powering."
    if call_trigger "${RESEND_SVC}" 20; then
        sleep 3
        if ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null | grep -q 'data: true'; then
            log "external control active again."
        else
            log "resend sent, robot_program_running not true yet - the next run checks again (cooldown ${RESEND_COOLDOWN}s)."
        fi
    else
        log "resend_robot_program failed - the next run checks again (cooldown ${RESEND_COOLDOWN}s)."
    fi
}

# 1) Is the arm reachable at all? No -> deliberately do nothing (the arm is still
#    off; the watchdog should fire ONLY on a late power-up or after a driver
#    failure, not constantly).
if ! ping -c1 -W1 "$ROBOT_IP" >/dev/null 2>&1; then
    exit 0
fi

# 2) Health check: is the PC-side motion link alive? The signal is the JSC stream
#    on .../manipulators/joint_states (real arm joints, available only when the
#    ros2_control HW interface is activated). robot_program_running (true/false) is
#    NOT a sufficient signal (controller side, stays true with a dead PC-side motion
#    link). The grace timeout is generous: after a manipulators restart the JSC
#    takes up to ~15s -> only >JS_TIMEOUT without a message means really dead.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
    ensure_external_control    # the JSC read path is ok - but is the write path up too?
    exit 0
fi
# Fallback: the arm joints can also arrive on the platform bus - namely when the
# stock patch move_arm_joint_states (clearpath-custom-setup.py step 3) no longer
# takes effect after an apt update. Without this branch the watchdog would read
# silence on a PERFECTLY HEALTHY robot and restart the driver permanently at the
# cooldown rate. The health signal is "arm joints arrive" - on whichever bus.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${PLATFORM_JS_TOPIC}'" 2>/dev/null \
     | grep -q 'arm_0_shoulder_pan_joint'; then
    log "WARN: arm joints arrive on ${PLATFORM_JS_TOPIC} instead of ${JS_TOPIC} -> the stock patch move_arm_joint_states does NOT take effect (apt update?). The motion link is HEALTHY, no recovery. Check: journalctl -t clearpath-custom-setup -b"
    exit 0
fi

# 3) Check the cooldown (/run is cleared at boot -> fresh per boot).
now="$(date +%s)"
if [ -f "$STATE" ]; then
    last="$(cat "$STATE" 2>/dev/null || echo 0)"
    [ -n "$last" ] || last=0
    if [ "$(( now - last ))" -lt "$COOLDOWN" ]; then
        log "motion link dead (JSC silent), but the last recovery was < ${COOLDOWN}s ago -> waiting."
        exit 0
    fi
fi

log "arm reachable (${ROBOT_IP}), but JSC ${JS_TOPIC} silent (motion link dead) -> recovery: restart ${SERVICE} + restart external control. NO automatic powering of the arm (operator decision)."
echo "$now" > "$STATE"

# 3a) Ensure clearpath-custom-ur-dashboard.service (the mode query and the resend
#     need the dashboard client; independent of manipulators, it stays up).
if [ "$(systemctl is-active "$DASH_SVC" 2>/dev/null)" != "active" ]; then
    log "${DASH_SVC} not active -> starting it."
    systemctl start "$DASH_SVC" || true
    sleep 3
fi

# 3b) Arm switched off on purpose? NO auto recovery and NO auto powering - the
#     watchdog NEVER powers the arm itself (operator decision; it protects
#     maintenance/end of day). It additionally prevents an endless driver restart
#     against an unpowered arm (the HW activation fails anyway -> the JSC would
#     stay silent -> loop).
rm_mode="$(robot_mode)"
if [ "$rm_mode" = "Robotmode: POWER_OFF" ]; then
    log "the arm is POWER_OFF (deliberately unpowered) -> no auto recovery, no powering. Power it up by hand if needed; the watchdog connects the motion link as soon as the arm is on."
    exit 0
fi

# 3c) Restart the driver (blocking). With the SIGINT stop drop-in on
#     clearpath-manipulators.service (see below, WD_MANIP_DROPIN) the old
#     ros2_control_node dies cleanly (the reverse socket is closed in an orderly
#     way) instead of ignoring SIGTERM for up to 90s -> the new controller manager
#     starts against a free socket. TimeoutStartSec of the watchdog service (300s)
#     covers a slow stop plus the recovery.
if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN=1 -> would have restarted ${SERVICE} now + resent external control. No intervention."
    exit 0
fi
systemctl restart "$SERVICE" || log "systemctl restart ${SERVICE} did not run cleanly - continuing the recovery anyway."

# 3d) Safety check: a protective/safety stop is NOT auto-cleared (manual only).
#     During a safety stop there is no resend (the operator must release first).
sm="$(safety_mode)"
if [ "$sm" != "Safetymode: NORMAL" ]; then
    log "the safety mode is '${sm:-unknown}' (not NORMAL) -> protective/safety stop. NOT auto-cleared, resend skipped. Manual inspection needed."
    exit 0
fi

# 3e) Restart external control directly (resend_robot_program) - with retries,
#     because the new manipulators CM needs a few seconds until
#     io_and_status_controller is active, and service discovery can be sluggish
#     under rmw_zenoh. A direct call instead of a ros2-service-list poll (the
#     latter is unreliable under rmw_zenoh). If the ur_state_manager runs along,
#     its auto_recover resets in parallel; a double resend is idempotent (the
#     program already runs -> success without effect).
sent=""
for attempt in 1 2 3 4 5 6; do
    if call_trigger "${RESEND_SVC}" 20; then
        log "resend_robot_program sent (attempt ${attempt})."
        sent=1; break
    fi
    log "resend attempt ${attempt} failed; retrying."
    sleep 3
done
if [ -z "$sent" ]; then
    log "resend_robot_program failed after 6 attempts - external control not restarted. Next timer run (cooldown ${COOLDOWN}s)."
    exit 0
fi

# 3f) Verify success: the JSC streams again (real arm joints). More reliable than
#     rpr, because it confirms the PC-side motion link directly (not only the
#     controller-side program). Short - the resend started external control, the
#     JSC becomes active quickly.
ok=""
for i in $(seq 1 "${RPR_WAIT}"); do
    if ros_cmd "timeout 6 ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
        ok=1; break
    fi
    sleep 1
done
if [ -n "$ok" ]; then
    log "recovery successful: ${JS_TOPIC} streams again."
else
    log "resend sent, but ${JS_TOPIC} still silent. The next timer run checks again (cooldown ${COOLDOWN}s)."
fi
WD_EOF
    chmod 0755 "$WD_WRAPPER"

    cat > "$WD_UNIT_PATH" <<EOF
[Unit]
Description=Watchdog check: restart clearpath-manipulators when the arm is reachable but the UR driver is not connected
# Only check after the driver; NO Wants/PartOf (a purely periodic check, it must
# not start or stop the driver along with it).
After=clearpath-manipulators.service

[Service]
Type=oneshot
# Runs as root (the default) -> may systemctl restart. The ROS check in the
# wrapper switches to ${REAL_USER} itself via 'sudo -u'.
ExecStart=${WD_WRAPPER} ${WD_ROBOT_IP} ${WD_PROGRAM_TOPIC} ${REAL_USER} ${USER_HOME}
# The recovery blocks on the systemctl restart plus dashboard calls and polls.
# With the SIGINT stop drop-in (WD_MANIP_DROPIN) the driver stops in ~1-3s;
# without the drop-in SIGTERM can take up to 90s until SIGKILL. The systemd
# default timeout (90s) would kill the oneshot midway -> generous (headroom for a
# slow stop plus the recovery).
TimeoutStartSec=300
# The script's echo lines are collectable under journalctl -t manipulators-watchdog.
SyslogIdentifier=manipulators-watchdog
EOF
    chmod 0644 "$WD_UNIT_PATH"

    cat > "$WD_TIMER_PATH" <<EOF
[Unit]
Description=Periodic manipulators-watchdog check (driver reconnect on a late arm power-up OR a stuck reconnect after a service restart)

[Timer]
# Start only after the normal boot ramp-up time (give the driver time), then
# regularly. A cadence of 10s (instead of 30s): that way the watchdog also fires
# within ~10s after a clearpath-robot.service restart with the arm already
# powered, as soon as the JSC stream (the health signal) stops. The grace timeout
# in the script (JS_TIMEOUT=25s) prevents false alarms during the ~15s
# manipulators ramp-up.
OnBootSec=90
OnUnitActiveSec=10
AccuracySec=2

[Install]
WantedBy=timers.target
EOF
    chmod 0644 "$WD_TIMER_PATH"

    # --- SIGINT stop drop-in for clearpath-manipulators.service -------------
    # ROS nodes (ros2_control_node, move_group, robot_state_pub) react to SIGINT
    # with a clean graceful ROS shutdown (the reverse/dashboard socket is closed in
    # an orderly way) instead of ignoring SIGTERM for up to 90s. Prevents the
    # socket collision on the reconnect after a service restart with the arm
    # already powered (the old external control instance holds the reverse socket
    # -> the new HW activation fails -> the arm goes flat in RViz). The drop-in
    # layers over the Clearpath unit (/usr/lib/systemd/system/...) and survives
    # package updates.
    install -d -m 0755 "$WD_MANIP_DROPIN_DIR"
    cat > "$WD_MANIP_DROPIN" <<'DROPEOF'
[Unit]
Description=Hard stop parameters for clearpath-manipulators (a clean driver shutdown)

[Service]
KillSignal=SIGINT
TimeoutStopSec=95
KillMode=control-group
SendSIGKILL=yes
# ros2_control_node puts its control thread on SCHED_FIFO via
# configure_sched_fifo() (default priority 50). Systemd units do NOT read
# /etc/security/limits.conf (pam_limits only applies to login sessions) -> without
# LimitRTPRIO that fails with EPERM and the loop runs SCHED_OTHER.
# Measured 2026-07-29: overruns at 125 Hz (cycles up to 18.5 ms).
LimitRTPRIO=99
DROPEOF
    chmod 0644 "$WD_MANIP_DROPIN"
else
    echo ">>> manipulators-watchdog: skipped."
fi

# --- joint-states aggregation + legacy bus relays ----------------
# Starts rg6_control/joint_states.launch.py: joint_state_aggregator
# (-> /a200_0553/joint_states, complete, for rosbag/Foxglove) plus the OWN
# joint_state_relay (manipulators/joint_states and
# manipulators/endeffectors/joint_states -> platform/joint_states, so that RSP and
# move_group run unchanged).  Deliberately NOT topic_tools: that publishes
# best-effort, move_group subscribes RELIABLE -> the joints would never arrive
# there (the reasoning sits at the head of joint_state_relay.cpp).
# Prerequisite: the arm JSB remap is switched to manipulators/joint_states (patch
# move_arm_joint_states in clearpath-custom-setup.py) and the gripper publishes on
# manipulators/endeffectors/joint_states -- which rg6_grip_bridge does (5 Hz).
echo ">>> Installing ${JS_WRAPPER} + ${JS_UNIT}"
cat > "$JS_WRAPPER" <<EOF
#!/usr/bin/env bash
# Robot-wide joint_states aggregation + legacy bus relays (see joint_states.launch.py).
source /etc/clearpath/setup.bash
source ${RG6_WS}/install/setup.bash
exec ros2 launch rg6_control joint_states.launch.py
EOF
chmod 0755 "$JS_WRAPPER"

cat > "$JS_UNIT_PATH" <<EOF
[Unit]
Description=Robot-wide joint_states aggregation + legacy bus relays
# Needs the source topics: wheels (clearpath-platform) + arm
# (clearpath-manipulators) + gripper (${RG6_BRIDGE_UNIT}). The gripper source is
# the bridge. An After= on a name that does not exist orders against nothing:
# systemd carries it without complaint, and the ordering this is about would be
# gone unnoticed.
# PartOf: the relay/aggregator (the custom rg6_control nodes joint_state_relay/
# joint_state_aggregator) does NOT resubscribe reliably under rmw_zenoh when the
# source publishes anew after a restart -> without restarting along, the rg6
# joints drop out of the TF feed and the gripper TF goes flat. That is why the
# unit also hangs off the bridge: a mere bridge restart is exactly that case.
# The arm relay is unaffected (the arm JSC goes straight into
# manipulators/joint_states).
After=clearpath-platform.service clearpath-manipulators.service ${RG6_BRIDGE_UNIT}
Wants=clearpath-platform.service
# Restart along against BOTH roots (robot + manipulators): PartOf propagates
# stop/restart only one hop and only on a DIRECT job. A stack restart via
# 'systemctl restart clearpath-robot' starts clearpath-manipulators only
# indirectly -> without PartOf=clearpath-robot the rg6 joint relays/aggregators
# would not restart along -> the gripper TF goes flat. Stopping clearpath-robot
# stops it too.
# ${RG6_BRIDGE_UNIT} is in the list because the bridge is the gripper source and
# restarts on its own (Restart=on-failure, or by hand) -- without this entry the
# relay survives the change but does not resubscribe.
PartOf=clearpath-robot.service clearpath-manipulators.service ${RG6_BRIDGE_UNIT}

[Service]
User=${REAL_USER}
ExecStart=${JS_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$JS_UNIT_PATH"

# --- octomap feed (optional): the dense obstacle layer for move_group ------
# Step 2 of the HRL obstacle architecture: move_group maintains an octomap
# (occupancy map monitor) from the wrist D435 and thereby also avoids obstacles
# the offboard object tracker does not (or does not yet) know about -- raycasts
# clear freed space automatically.  This service delivers the throttled
# PointCloud2 (octomap_feed.py, default 5 Hz / stride 2); the move_group sensor
# parameters come from robot.yaml.  Uninstalling: 'systemctl disable --now
# clearpath-custom-octomap-feed', delete the unit file, reboot.
DO_OCTO=1
if [ -f "$OCTO_UNIT_PATH" ]; then
    confirm ">>> ${OCTO_UNIT} is already installed. Update?" || DO_OCTO=0
else
    confirm ">>> Install the octomap feed (move_group then also avoids untracked obstacles; ~5 Hz onboard load)?" || DO_OCTO=0
fi
if [ "$DO_OCTO" -eq 1 ]; then
    echo ">>> Installing ${OCTO_FEED_BIN}"
    # repo_file takes the checked-out state BEFORE GitHub main (ROBOTER-TODO archive R6).
    # The other way round, a run from the checkout would silently install
    # something other than what is in the checkout - exactly how the
    # octomap_feed drift across three versions came about.  If the file found is
    # broken, it is DISCARDED and not quietly replaced by main: a broken
    # checkout should be noticed.
    OCTO_SRC=""
    if OCTO_CAND="$(repo_file scripts/octomap_feed.py)"; then
        if python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$OCTO_CAND"; then
            OCTO_SRC="$OCTO_CAND"
        else
            echo "    WARN: $OCTO_CAND is not valid Python - discarding it."
        fi
    else
        echo "    WARN: scripts/octomap_feed.py found neither in the checkout nor under ${SETUP_WS} nor on GitHub."
    fi
    if [ -n "$OCTO_SRC" ]; then
        install -m 0755 -o root -g root "$OCTO_SRC" "$OCTO_FEED_BIN"
        # Selftest of the conversion (numpy only, no ROS needed).
        python3 "$OCTO_FEED_BIN" --selftest || echo "    WARN: selftest failed - the service is installed anyway (check the logs)."

        echo ">>> Installing ${OCTO_WRAPPER} + ${OCTO_UNIT}"
        cat > "$OCTO_WRAPPER" <<EOF
#!/usr/bin/env bash
# Throttled depth->PointCloud2 source for MoveIt's octomap (octomap_feed).
source /etc/clearpath/setup.bash
exec python3 ${OCTO_FEED_BIN}
EOF
        chmod 0755 "$OCTO_WRAPPER"

        cat > "$OCTO_UNIT_PATH" <<EOF
[Unit]
Description=Octomap feed: depth -> PointCloud2 for MoveIt's occupancy map monitor
After=clearpath-sensors.service
Wants=clearpath-sensors.service
# Stack restart behaviour as for the other custom units: hang off both roots
# (the practical stack restart goes through clearpath-robot).
PartOf=clearpath-robot.service clearpath-sensors.service

[Service]
User=${REAL_USER}
ExecStart=${OCTO_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        chmod 0644 "$OCTO_UNIT_PATH"
        # A pure CHECK (no apt!): the PointCloudOctomapUpdater comes from
        # moveit_ros_perception. Without that package the feed still runs, but
        # move_group has no updater to hand the cloud to - installing it is an
        # admin decision.
        if ! ls -d /opt/ros/*/share/moveit_ros_perception >/dev/null 2>&1; then
            echo "    WARN: ros-<distro>-moveit-ros-perception is NOT installed."
            echo "          The octomap stays inactive until the package is there."
            echo "          Install it ONLY deliberately, in a maintenance window (mind the"
            echo "          apt history of this robot; check with 'apt-get install -s' first)."
        fi
    else
        echo "    WARN: octomap_feed.py neither loadable nor present locally - octomap skipped."
    fi
else
    echo ">>> Octomap feed: skipped."
fi

# --- manipulator diagnostics (optional) ------------------------------------
# UR mode/safety/external control + RG6 state -> diagnostic_msgs on the
# /diagnostics topic of the Clearpath aggregator. The matching aggregator
# analyzer comes from robot.yaml, unconditionally: without this node, Cockpit
# shows the group as STALE instead of letting it vanish.
# Uninstalling: 'systemctl disable --now clearpath-custom-manipulator-diagnostics',
# delete the unit file, reboot.
DO_MD=1
if [ -f "$MD_UNIT_PATH" ]; then
    confirm ">>> ${MD_UNIT} is already installed. Update?" || DO_MD=0
else
    confirm ">>> Install the manipulator diagnostics (UR5 + RG6 then appear in Cockpit/diagnostics_agg)?" || DO_MD=0
fi
if [ "$DO_MD" -eq 1 ]; then
    echo ">>> Installing ${MD_BIN}"
    # repo_file takes the checked-out state BEFORE GitHub main (ROBOTER-TODO archive R6).
    # The other way round, a run from the checkout would silently install
    # something other than what is in the checkout - exactly how the
    # octomap_feed drift across three versions came about.  If the file found is
    # broken, it is DISCARDED and not quietly replaced by main: a broken
    # checkout should be noticed.
    MD_SRC=""
    if MD_CAND="$(repo_file scripts/manipulator_diagnostics.py)"; then
        if python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$MD_CAND"; then
            MD_SRC="$MD_CAND"
        else
            echo "    WARN: $MD_CAND is not valid Python - discarding it."
        fi
    else
        echo "    WARN: scripts/manipulator_diagnostics.py found neither in the checkout nor under ${SETUP_WS} nor on GitHub."
    fi
    if [ -n "$MD_SRC" ]; then
        install -m 0755 -o root -g root "$MD_SRC" "$MD_BIN"
        # Selftest of the evaluation logic (pure Python, no ROS needed).
        python3 "$MD_BIN" --selftest || echo "    WARN: selftest failed - the service is installed anyway (check the logs)."

        echo ">>> Installing ${MD_WRAPPER} + ${MD_UNIT}"
        cat > "$MD_WRAPPER" <<EOF
#!/usr/bin/env bash
# UR5 + OnRobot RG6 as diagnostic_msgs for the Clearpath diagnostic_aggregator.
# No onrobot-rg6 overlay needed: the gripper state arrives as JSON from the
# bridge (rg6/bridge_state), so std_msgs is enough -- onrobot-rg6 ships no
# interface package at all.
source /etc/clearpath/setup.bash
exec python3 ${MD_BIN} --ros-args \\
    -p manipulator_ns:=${MANIP_NS} \\
    -p robot_ip:=${ARM_ROBOT_IP}
EOF
        chmod 0755 "$MD_WRAPPER"

        cat > "$MD_UNIT_PATH" <<EOF
[Unit]
Description=Manipulator diagnostics: UR5 + RG6 -> diagnostic_msgs (Cockpit/diagnostics_agg)
After=clearpath-manipulators.service ${RG6_BRIDGE_UNIT}
Wants=clearpath-manipulators.service
# Hang off BOTH roots: the practical stack restart goes through clearpath-robot,
# the direct driver restart through clearpath-manipulators.
PartOf=clearpath-robot.service clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${MD_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        chmod 0644 "$MD_UNIT_PATH"
    else
        echo "    WARN: manipulator_diagnostics.py neither loadable nor present locally - manipulator diagnostics skipped."
    fi
else
    echo ">>> Manipulator diagnostics: skipped."
fi

# --- RTDE input recipe without the tool DO ---------------------------------
# The prerequisite for the ur_robot_driver to start alongside the OnRobot URCap
# at all: the URCap is an RTDE client itself and occupies
# tool_digital_output_mask, otherwise the driver dies during the RTDE setup with
# "controlled by another RTDE client". robot.yaml points FIXEDLY at
# /home/robot/rtde_input_recipe_no_tool.txt -- if the file is missing after a
# reinstall, the driver does not start, and without any hint at it.
RTDE_RECIPE_DST="${USER_HOME}/rtde_input_recipe_no_tool.txt"
if RTDE_RECIPE_SRC="$(repo_file rtde_input_recipe_no_tool.txt)"; then
    if [ "$RTDE_RECIPE_SRC" -ef "$RTDE_RECIPE_DST" ]; then
        # Source and target are the same file -- this happens when the installer
        # runs out of ${USER_HOME}.  install(1) then aborts, and with set -e it
        # takes the whole run along.  There is simply nothing to do here.
        echo ">>> RTDE recipe is already in place (${RTDE_RECIPE_DST})"
    else
        install -m 0644 -o "$REAL_USER" -g "$REAL_USER" \
            "$RTDE_RECIPE_SRC" "$RTDE_RECIPE_DST"
        echo ">>> RTDE recipe ─▶ ${RTDE_RECIPE_DST}  (from ${RTDE_RECIPE_SRC})"
    fi
else
    echo "    WARN: rtde_input_recipe_no_tool.txt neither local nor retrievable -"
    echo "          the UR driver does NOT start without it."
fi

# --- RG6 gripper bridge (XML-RPC to the OnRobot URCap) --------------------
# The recipe above takes the tool DO path out: ROS can no longer set a tool DO,
# so this node commands the gripper directly over XML-RPC (rg_grip on
# 192.168.131.40:41414). It runs ONBOARD because the endpoint hangs off the arm
# subnet -- from the workstation there is no route to it -- and because the robot
# must be able to grip without the radio link too.
RG6_KIN_DST="${BIN_DIR}/rg6_finger_kinematics.json"

DO_RG6_BRIDGE=1
if [ -f "$RG6_BRIDGE_UNIT_PATH" ]; then
    confirm ">>> ${RG6_BRIDGE_UNIT} is already installed. Update?" || DO_RG6_BRIDGE=0
else
    confirm ">>> Install the RG6 gripper bridge (commands the gripper over XML-RPC to the OnRobot URCap)?" || DO_RG6_BRIDGE=0
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    if ! RG6_SRC="$(repo_file scripts/rg6_grip_bridge.py)"; then
        echo "    WARN: scripts/rg6_grip_bridge.py neither local nor retrievable -"
        echo "          RG6 bridge skipped."
        DO_RG6_BRIDGE=0
        RG6_SRC=""
    elif ! python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$RG6_SRC"; then
        echo "    WARN: ${RG6_SRC} is not valid Python - discarding it."
        DO_RG6_BRIDGE=0
    fi
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    # The linkage table (joint angle -> grip width).  It sits here instead of an
    # import from robot_contract: that package is PRIVATE and not even clonable
    # from the robot (git asks for credentials) -- a dependency that prevents the
    # roll-out secures nothing.
    # The file is generated from the GENERATED URDF, see
    # onrobot-rg6/tools/derive_finger_kinematics.py.  Without it the node does
    # not start: with no kinematics it can neither publish the finger joint nor
    # translate a GripperCommand goal into a width.
    if RG6_KIN_SRC="$(repo_file scripts/rg6_finger_kinematics.json)"; then
        install -m 0644 -o root -g root "$RG6_KIN_SRC" "$RG6_KIN_DST"
        echo "    linkage table ─▶ ${RG6_KIN_DST}  (from ${RG6_KIN_SRC})"
    else
        echo "    WARN: rg6_finger_kinematics.json missing - the node does NOT start without it."
        DO_RG6_BRIDGE=0
    fi
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    echo ">>> Installing ${RG6_BRIDGE_BIN}"
    install -m 0755 -o root -g root "$RG6_SRC" "$RG6_BRIDGE_BIN"
    # Selftest without ROS -- units, float coercion, clamping, timeout, the wire
    # contract, the linkage, concurrency.
    python3 "$RG6_BRIDGE_BIN" --selftest \
        || echo "    WARN: selftest failed - the service is installed anyway (check the logs)."

    cat > "$RG6_BRIDGE_WRAPPER" <<EOF
#!/usr/bin/env bash
# RG6 gripper over XML-RPC to the OnRobot URCap (rg6_grip_bridge).
source /etc/clearpath/setup.bash
exec python3 ${RG6_BRIDGE_BIN}
EOF
    chmod 0755 "$RG6_BRIDGE_WRAPPER"

    cat > "$RG6_BRIDGE_UNIT_PATH" <<EOF
[Unit]
Description=RG6 gripper bridge (XML-RPC to the OnRobot URCap)
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service
PartOf=clearpath-robot.service clearpath-manipulators.service
# WITHOUT these two a broken unit spins FOREVER: the systemd default is burst=5
# in 10 s, and with RestartSec=5 only two attempts fit into that -- so the limit
# is never reached. Worked out on 2026-08-17. 120 s, because five attempts at 5 s
# take about 25 s; the unit then stays visibly 'failed' instead of hiding
# itself.
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User=${REAL_USER}
ExecStart=${RG6_BRIDGE_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$RG6_BRIDGE_UNIT_PATH"
    systemctl daemon-reload
    systemctl enable "$RG6_BRIDGE_UNIT" >/dev/null 2>&1 \
        || echo "    WARN: systemctl enable ${RG6_BRIDGE_UNIT} failed."
    echo ">>> ${RG6_BRIDGE_UNIT} installed and enabled."
else
    echo ">>> RG6 gripper bridge: skipped."
fi

# --- Cockpit plugin with the manipulator panel (optional) -------------------
# Fork of clearpathrobotics/cockpit-ros2-diagnostics: in addition to the generic
# diagnostics tree, its own manipulator view (arm mode/safety/external
# control/motion link + joint table, gripper width/grip_detected/tool power). The
# data comes from the same diagnostics_agg stream -- without the
# manipulator-diagnostics service above the panel stays invisible.
#
# Installed to /usr/local/share/cockpit/ros2-diagnostics: Cockpit prefers
# /usr/local over /usr/share, so the fork shadows the apt package without
# replacing it. Rollback = delete the directory (no apt).
# NOTE: apt updates of cockpit-ros2-diagnostics then have no visible effect as
# long as the fork is there - update the fork when needed.
DO_CKPT=1
if [ -d "$CKPT_PKG_DIR" ]; then
    confirm ">>> The Cockpit plugin (fork with the manipulator panel) is installed. Update?" || DO_CKPT=0
else
    confirm ">>> Install the Cockpit plugin with the manipulator panel (shadows the apt plugin under /usr/share)?" || DO_CKPT=0
fi
if [ "$DO_CKPT" -eq 1 ]; then
    if ! dpkg -s cockpit-bridge >/dev/null 2>&1; then
        echo "    WARN: cockpit-bridge is not installed - the plugin only becomes visible after Cockpit is installed."
    fi
    echo ">>> cockpit-ros2-diagnostics (fork) to ${CKPT_WS} (user ${REAL_USER})"
    CKPT_OK=1
    if [ -d "${CKPT_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$CKPT_WS" pull --ff-only || echo "    WARN: git pull failed, using the existing state"
    else
        sudo -u "$REAL_USER" git clone "$CKPT_REPO_URL" "$CKPT_WS" || CKPT_OK=0
    fi
    if [ "$CKPT_OK" -eq 1 ]; then
        # Prefers a prebuilt dist/ from the checkout. The build needs nodejs+npm
        # (~500 packages) and a git fetch of the Cockpit library -- that
        # deliberately does NOT belong on the robot when it is avoidable (mind the
        # apt history of this robot). The installer therefore installs no nodejs;
        # it only builds when the toolchain is already there.
        if [ ! -f "${CKPT_WS}/dist/manifest.json" ]; then
            if command -v npm >/dev/null 2>&1 && command -v make >/dev/null 2>&1; then
                echo ">>> No prebuilt dist/ - building on the robot (npm + make)"
                sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
                    "cd '$CKPT_WS' && make" || CKPT_OK=0
            else
                echo "    WARN: neither dist/ nor npm/make present."
                echo "          Build it on a machine WITH the toolchain and bring the result over:"
                echo "            git clone ${CKPT_REPO_URL} && cd cockpit-ros2-diagnostics && make"
                echo "            rsync -a dist/ ${REAL_USER}@<robot>:${CKPT_WS}/dist/"
                echo "          Then run this installer again."
                CKPT_OK=0
            fi
        fi
    fi
    if [ "$CKPT_OK" -eq 1 ] && [ -f "${CKPT_WS}/dist/manifest.json" ]; then
        echo ">>> Installing the plugin to ${CKPT_PKG_DIR}"
        # Remove the old content so that deleted files do not linger.
        rm -rf "$CKPT_PKG_DIR"
        install -d -m 0755 "$CKPT_PKG_DIR"
        cp -r "${CKPT_WS}/dist/." "$CKPT_PKG_DIR/"
        chown -R root:root "$CKPT_PKG_DIR"
        # Source maps are large and useless on the robot (the Debian package
        # throws them away too).
        find "$CKPT_PKG_DIR" -name '*.map' -delete
        echo "    Reload Cockpit: a browser reload on http://<robot>:9090 is enough."
    else
        echo "    WARN: Cockpit plugin not installed (see the messages above) - the apt plugin stays active."
    fi
else
    echo ">>> Cockpit plugin: skipped."
fi

# --- enable ----------------------------------------------------------------
echo ">>> Reloading systemd + enabling the services (+ starting them, not only the boot symlink)"
systemctl daemon-reload
# enable --now: activates the boot symlink AND starts the unit IMMEDIATELY.
# Important on a running system: plain 'enable' would start the units only on the
# next reboot -> the whole custom stack (including ur-state-manager/auto_recover
# and the watchdog timer) would stay dead until then.
# Wants=clearpath-manipulators pulls the driver up if it is not running yet;
# After= secures the ordering.
systemctl enable --now "$UNIT_NAME" "$JS_UNIT"
[ -f "$UR_DASH_UNIT_PATH" ] && systemctl enable --now "$UR_DASH_UNIT"
[ -f "$USM_UNIT_PATH" ] && systemctl enable --now "$USM_UNIT"
# Watchdog: enable + start the TIMER (the .service is the oneshot check it triggers).
[ -f "$WD_TIMER_PATH" ] && systemctl enable --now "$WD_TIMER"
[ -f "$OCTO_UNIT_PATH" ] && systemctl enable --now "$OCTO_UNIT"
[ -f "$MD_UNIT_PATH" ] && systemctl enable --now "$MD_UNIT"
# Start the bridge IMMEDIATELY too, not only on the next boot: without it
# rg6_finger_joint is missing from /joint_states, and until the reboot move_group
# plans against a hand in its default pose (R22 in the ROBOTER-TODO archive).
[ -f "$RG6_BRIDGE_UNIT_PATH" ] && systemctl enable --now "$RG6_BRIDGE_UNIT"

echo ">>> Checking the unit syntax"
VERIFY_UNITS=("$UNIT_PATH" "$JS_UNIT_PATH")
[ -f "$UR_DASH_UNIT_PATH" ] && VERIFY_UNITS+=("$UR_DASH_UNIT_PATH")
[ -f "$USM_UNIT_PATH" ] && VERIFY_UNITS+=("$USM_UNIT_PATH")
[ -f "$WD_UNIT_PATH" ] && VERIFY_UNITS+=("$WD_UNIT_PATH" "$WD_TIMER_PATH")
[ -f "$OCTO_UNIT_PATH" ] && VERIFY_UNITS+=("$OCTO_UNIT_PATH")
[ -f "$MD_UNIT_PATH" ] && VERIFY_UNITS+=("$MD_UNIT_PATH")
[ -f "$RG6_BRIDGE_UNIT_PATH" ] && VERIFY_UNITS+=("$RG6_BRIDGE_UNIT_PATH")
systemd-analyze verify "${VERIFY_UNITS[@]}" && echo "    units OK."

# --- apply the patches once now --------------------------------------------
# The guard is robot.yaml: it proves that /etc/clearpath is set up, and unlike a
# generated file it holds no matter which steps the patcher currently performs.
# The steps themselves are individually guarded against missing files.
if [ -f "$ROBOT_YAML_PATH" ]; then
    echo ">>> Applying the config patches once now"
    "$PY_PATH" || true
fi

echo
echo "=============================================================="
echo "Installation complete."
echo "  ${UNIT_NAME} : patches the configs on every boot"
echo "  ${ROBOT_YAML_PATH} ─▶ ${SETUP_WS}/robot.yaml (symlink, SSOT in the repo)"
echo "  ${JS_UNIT}           : joint_state_aggregator + legacy bus relays"
echo "  ${SYSCTL_UR_PORTS} : UR driver ports 50001-50004 out of the ephemeral range"
[ -f "$RTDE_RECIPE_DST" ] && \
echo "  ${RTDE_RECIPE_DST} : RTDE input recipe without the tool DO (the UR driver needs it next to the URCap)"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  ${UR_DASH_UNIT}           : starts the ur_robot_driver dashboard_client"
[ -f "$USM_UNIT_PATH" ] && \
echo "  ${USM_UNIT}       : starts ur_state_manager (prepare/recover) + extra controllers + mode manager"
[ -f "$WD_TIMER_PATH" ] && \
echo "  ${WD_TIMER}    : driver reconnect on a late arm power-up OR a stuck reconnect after a service restart (health signal = JSC stream, cadence 10s)"
echo "  clearpath-manipulators.service.d/override.conf : SIGINT stop drop-in (clean driver shutdown, prevents the socket collision on reconnect)"
[ -f "$RG6_MOVEIT_PATCH_BIN" ] && \
echo "  ${RG6_MOVEIT_PATCH_BIN}     : root-owned copy of rg6_moveit_patch (used by the boot service, updated only by the installer)"
[ -f "$OCTO_UNIT_PATH" ] && \
echo "  ${OCTO_UNIT}   : depth─▶PointCloud2 for MoveIt's octomap (the move_group sensor parameters come from robot.yaml)"
[ -f "$MD_UNIT_PATH" ] && \
echo "  ${MD_UNIT} : UR5 + RG6 ─▶ diagnostic_msgs (the analyzers come from robot.yaml)"
[ -f "$RG6_BRIDGE_UNIT_PATH" ] && \
echo "  ${RG6_BRIDGE_UNIT} : RG6 over XML-RPC to the OnRobot URCap (grip commands, finger joint, gripper state)"
[ -d "$CKPT_PKG_DIR" ] && \
echo "  ${CKPT_PKG_DIR} : Cockpit plugin with the manipulator panel (shadows the apt plugin under /usr/share)"
echo
echo "For EVERYTHING to take effect, restart once:"
echo "  sudo systemctl restart clearpath-robot   # or reboot"
echo
echo "Logs:"
echo "  journalctl -t clearpath-custom-setup -b"
echo "  journalctl -u ${JS_UNIT} -b"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  journalctl -u ${UR_DASH_UNIT} -b"
[ -f "$USM_UNIT_PATH" ] && \
echo "  journalctl -u ${USM_UNIT} -b"
[ -f "$WD_TIMER_PATH" ] && \
echo "  journalctl -t manipulators-watchdog -b   # + 'systemctl list-timers ${WD_TIMER}'"
[ -f "$OCTO_UNIT_PATH" ] && \
echo "  journalctl -u ${OCTO_UNIT} -b"
[ -f "$MD_UNIT_PATH" ] && \
echo "  journalctl -u ${MD_UNIT} -b   # + 'ros2 topic echo ${MANIP_NS%/manipulators}/diagnostics_agg'"
[ -f "$RG6_BRIDGE_UNIT_PATH" ] && \
echo "  journalctl -u ${RG6_BRIDGE_UNIT} -b   # + 'ros2 topic echo ${MANIP_NS}/rg6/bridge_state'"
echo
echo "Note: robot.yaml is managed from the git repo (SSOT)."
echo "  Maintain changes (platform.extras.urdf, system.ros2.workspaces, arm/sensor config)"
echo "  in the repo (${SETUP_WS}) - the symlink makes them effective IMMEDIATELY:"
echo "  clearpath-robot-check detects the change and restarts the stack."
echo "=============================================================="
