#!/usr/bin/env bash
#
# Fetch the individual factory calibration of the UR5 (DH offsets) into a YAML
# file.  Without it the model computes with nominal values and the real TCP is
# off by up to ~1 cm.
#
# NOT part of install-clearpath-custom-setup.sh, and deliberately so: this
# script installs PACKAGES and needs a powered arm -- it is a measurement
# procedure, not an installation step.  The installer writes files
# and units and installs no package at all; keeping this inside it meant that
# `install-clearpath-custom-setup.sh -y` answered the apt question with "yes"
# without anyone seeing it.
#
#   !! THIS RUNS apt-get install ON A ROBOT WHOSE UR STACK IS PINNED !!
#
# ur_calibration needs an ABI matching the ur_client_library.  Clearpath may
# have an older UR stack installed (driver/urcl), and the newest ur-calibration
# then does not fit (undefined symbol ...urcl...SafetyModeMessage, and 3.7.0 is
# no longer in the repo).  The only way that works is to install the WHOLE UR
# stack together, from one release -- which can pull ur-robot-driver up (3.7.0
# -> 3.8.0).  In testing it removed no Clearpath package.  Against that stands
# the standing rule for this robot: never apt-upgrade blindly (ros2_control/UR
# version breaks), which an apt pin on a frozen ROS snapshot repo enforces.
# So: run this in a maintenance window, with time to test the manipulator
# afterwards, and read `apt-get install -s` first if in doubt.
#
# Usage:
#   bash tools/ur-calibrate.sh                     # defaults below
#   bash tools/ur-calibrate.sh --robot-ip 192.168.131.40 --out ~/ur5.yaml
#   bash tools/ur-calibrate.sh --skip-apt          # the UR stack is already right
#
# By default it overwrites config/ur5_a200_0553_calibration.yaml in this checkout, the file robot.yaml names as
# kinematics_parameters_file: `git diff` then compares the new measurement with the committed one, and a commit
# makes it the arm's.  It takes effect when the Clearpath stack restarts (reboot).  With --out somewhere else,
# robot.yaml has to name that file instead -- it is hand maintained, nothing here touches it.

set -euo pipefail

ROBOT_IP="192.168.131.40"
OUT_FILE=""
SKIP_APT=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --robot-ip) ROBOT_IP="${2:?--robot-ip needs a value}"; shift 2 ;;
        --out)      OUT_FILE="${2:?--out needs a value}"; shift 2 ;;
        --skip-apt) SKIP_APT=1; shift ;;
        -h|--help)  awk 'NR>1 && /^[^#]/{exit} NR>1{sub(/^# ?/,""); print}' "$0"; exit 0 ;;
        *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
    esac
done

# The real user, not root -- the calibration launch runs in their ROS
# environment, and the file belongs to them afterwards.
REAL_USER="${SUDO_USER:-robot}"
USER_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
OUT_FILE="${OUT_FILE:-$(cd "$(dirname "$0")/.." && pwd)/config/ur5_a200_0553_calibration.yaml}"

if [ "$(id -u)" -ne 0 ] && [ "$SKIP_APT" -eq 0 ]; then
    echo "Need root privileges for apt-get - restarting via sudo ..."
    exec sudo -- bash "$0" --robot-ip "$ROBOT_IP" --out "$OUT_FILE"
fi

if [ "$SKIP_APT" -eq 0 ]; then
    echo ">>> Installing/updating the UR stack consistently (client-library + driver + calibration)"
    echo "    Mind the apt pin of this robot - see the header of this script."
    apt-get update || true
    apt-get install -y \
        ros-jazzy-ur-client-library ros-jazzy-ur-robot-driver ros-jazzy-ur-calibration \
        || echo "    WARN: UR stack installation failed."
fi

if ! dpkg -s ros-jazzy-ur-calibration >/dev/null 2>&1; then
    echo ">>> ur_calibration is not installed - nothing to calibrate with."
    echo "    Run without --skip-apt, or install ros-jazzy-ur-calibration by hand."
    exit 1
fi
if ! ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1; then
    echo ">>> UR arm ${ROBOT_IP} not reachable (ping) - calibration skipped."
    exit 1
fi

echo ">>> Calibrating the UR arm (${ROBOT_IP}) ─▶ ${OUT_FILE}"
echo "    Note: on 'Could not connect' the driver may occupy the interface ─▶"
echo "          'sudo systemctl stop clearpath-manipulators.service', then retry."
CALIB_CMD="source /opt/ros/jazzy/setup.bash && ros2 launch ur_calibration"
CALIB_CMD="${CALIB_CMD} calibration_correction.launch.py robot_ip:=${ROBOT_IP}"
CALIB_CMD="${CALIB_CMD} target_filename:='${OUT_FILE}'"
if [ "$(id -un)" = "$REAL_USER" ]; then
    RUN_AS=(env "HOME=$USER_HOME" bash -lc)
else
    RUN_AS=(sudo -u "$REAL_USER" env "HOME=$USER_HOME" bash -lc)
fi
if "${RUN_AS[@]}" "$CALIB_CMD"; then
    chown "$REAL_USER":"$REAL_USER" "$OUT_FILE" 2>/dev/null || true
    echo "    Calibration saved: ${OUT_FILE}"
    echo "    ─▶ robot.yaml has to name it as kinematics_parameters_file (the checkout's file it does);"
    echo "       compare with 'git diff', commit, and restart the Clearpath stack (reboot)."
else
    echo "    WARN: calibration failed (arm on/reachable? interface free?)."
    exit 1
fi
