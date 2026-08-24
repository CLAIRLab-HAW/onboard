#!/usr/bin/env bash
# shutdown.sh - drive the robot arm into the pose "packed" and shut the
#               installation down in a controlled way.
#
# Runs DIRECTLY on the robot PC (a200-0553) against the local ROS 2 graph.
# Sequence:
#   1. make the arm ready              (ur_state_manager/prepare, idempotent)
#   2. switch to trajectory mode       (ur_controller_mode_manager/mode/trajectory,
#                                       so that the JTC accepts the goal)
#   3. drive the arm to pose "packed"  (arm_0_joint_trajectory_controller,
#                                       absolute joint angles from robot.yaml)
#   4. power the arm down              (ur_state_manager/power_off)
#   5. stop the platform services      (clearpath-manipulators + clearpath-robot)
#   6. switch the robot PC off         (systemctl poweroff)
#
# Steps 5+6 need root (sudo). Step 6 is the irreversible part - it switches
# the whole robot PC off; hence there is a confirmation before it (skippable
# with -y / --yes).
#
# Options:
#   -y, --yes           no confirmation before poweroff
#   --no-poweroff       NO systemctl poweroff (only stop services, leave the PC on)
#   --no-services       do NOT stop the platform services (only park the arm + power_off)
#   --ns <namespace>    robot namespace (default: a200_0553 or $CLEARPATH_NS)
#   -h, --help          this help
#
# Env:
#   CLEARPATH_NS          robot namespace (default a200_0553)
#   SHUTDOWN_ARM_TIME     travel time to packed in s (default 10.0 - a large movement)
#   SHUTDOWN_GOAL_TIMEOUT max wait for the trajectory result in s (default 60)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
NS="${CLEARPATH_NS:-a200_0553}"
MANIP_NS="${NS}/manipulators"
ARM_TIME="${SHUTDOWN_ARM_TIME:-10.0}"
GOAL_TIMEOUT="${SHUTDOWN_GOAL_TIMEOUT:-60}"

# Pose "packed" from husky-custom-setup/robot.yaml (canonical UR order:
# shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3). Keep in sync
# here when robot.yaml changes (or use the generate_semantic_description path
# and drive by MoveIt group state).
PACKED_JOINTS=(
  -0.000695530568258107
  -3.1283000151263636
   2.8355469703674316
  -3.193974320088522
   1.5455983877182007
  -0.0000837484928349762
)
ARM_JOINTS=(
  arm_0_shoulder_pan_joint
  arm_0_shoulder_lift_joint
  arm_0_elbow_joint
  arm_0_wrist_1_joint
  arm_0_wrist_2_joint
  arm_0_wrist_3_joint
)

DO_YES=0
DO_POWEROFF=1
DO_SERVICES=1

# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------
usage() { sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        DO_YES=1; shift ;;
    --no-poweroff)   DO_POWEROFF=0; shift ;;
    --no-services)   DO_SERVICES=0; shift ;;
    --ns)            NS="$2"; MANIP_NS="${NS}/manipulators"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "shutdown: unknown option: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[shutdown]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[shutdown]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[shutdown]\033[0m %s\n' "$*" >&2; exit 1; }

run() { log "$*"; "$@"; }

# ---------------------------------------------------------------------------
# ROS environment
# ---------------------------------------------------------------------------
# The canonical entry point is /etc/clearpath/setup.bash: it sources the
# jazzy setup, onrobot-rg6 and - DECISIVELY - sets ROS_DOMAIN_ID and
# RMW_IMPLEMENTATION (rmw_zenoh_cpp). Without the latter the script runs in
# the ROS jazzy default (FastDDS) and is NOT in the same graph as the robot
# stacks -> ros2 service call hangs ("waiting for service to
# become available"). So try it BEFORE the bare /opt/ros path.
# ROS setup scripts touch variables that are unbound under `set -u`
# (e.g. AMENT_TRACE_SETUP_FILES) -> turn -u off while sourcing.
if [ -f /etc/clearpath/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /etc/clearpath/setup.bash; set -u
elif [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /opt/ros/jazzy/setup.bash; set -u
  # Fallback on non-Clearpath boxes: at least set the default domain plus the
  # RMW customary on Clearpath robots (zenoh), if not already set.
  : "${ROS_DOMAIN_ID:=0}";        export ROS_DOMAIN_ID
  : "${RMW_IMPLEMENTATION:=rmw_zenoh_cpp}"; export RMW_IMPLEMENTATION
else
  die "/etc/clearpath/setup.bash and /opt/ros/jazzy/setup.bash are missing - is shutdown.sh running on the robot PC?"
fi
# If there is a local workspace setup, source it as well (without failing).
for ws in /opt/ros/clearpath/setup.bash /opt/ros/robot/setup.bash \
          /home/robot/ros2_ws/install/setup.bash /ros2_ws/install/setup.bash; do
  [ -f "$ws" ] && { # shellcheck disable=SC1091
    set +u; source "$ws" || true; set -u; }
done

JTC_ACTION="/${MANIP_NS}/arm_0_joint_trajectory_controller/follow_joint_trajectory"
PREPARE_SRV="/${MANIP_NS}/ur_state_manager/prepare"
POWER_OFF_SRV="/${MANIP_NS}/ur_state_manager/power_off"
TRAJ_MODE_SRV="/${MANIP_NS}/ur_controller_mode_manager/mode/trajectory"

# ---------------------------------------------------------------------------
# ROS service helper: calls a std_srvs/Trigger and evaluates success.
# ---------------------------------------------------------------------------
call_trigger() {
  # std_srvs/Trigger has an EMPTY request (only bool success + string message on
  # the response) - pass no field. ros2 has no `service wait`, hence the hard
  # timeout around it (service absent -> ros2 service call would hang).
  local srv="$1" label="$2" timeout="${3:-30}"
  local secs="${timeout%.*}"   # float -> int (e.g. 30.0 -> 30) for bash arithmetic
  [ -z "$secs" ] && secs="$timeout"
  log "${label}: calling ${srv}"
  # Catch the exit code of timeout DIRECTLY via `|| rc=$?` - NOT `|| true`
  # inside the substitution and `rc=$?` afterwards: that reads the status of
  # the assignment (always 0), which would make the 124 branch dead code.
  local out rc=0
  out="$(timeout "$((secs + 15))" ros2 service call "$srv" std_srvs/srv/Trigger 2>&1)" || rc=$?
  if [ "$rc" -eq 124 ]; then
    warn "${label}: timeout - service ${srv} not reachable."
    return 1
  fi
  # ros2 service call prints the response as a Python repr
  # (`Trigger_Response(success=True, ...)`), NOT as YAML (`success: true`).
  # Accept both spellings, otherwise every success looks like a failure.
  echo "$out" | grep -qiE 'success[:=][[:space:]]*true' && { log "${label}: ok"; return 0; }
  warn "${label}: no success=true. Excerpt:"
  echo "$out" | tail -n 6 | sed 's/^/    /' >&2
  return 1
}

# ---------------------------------------------------------------------------
# 1. make the arm ready (idempotent)
# ---------------------------------------------------------------------------
log "step 1/6: preparing the arm (ur_state_manager/prepare)"
call_trigger "$PREPARE_SRV" "prepare" 30.0 || warn "prepare not successful - continuing the attempt."

# ---------------------------------------------------------------------------
# 2. activate trajectory mode (otherwise the JTC rejects the goal)
# ---------------------------------------------------------------------------
log "step 2/6: activating trajectory mode (mode/trajectory)"
call_trigger "$TRAJ_MODE_SRV" "mode/trajectory" 15.0 || warn "mode/trajectory not successful - attempting the movement anyway."

# ---------------------------------------------------------------------------
# 3. drive the arm to "packed" (absolute trajectory over the JTC)
# ---------------------------------------------------------------------------
log "step 3/6: driving the arm to pose 'packed' (${ARM_TIME}s)"

# Pass joint_names + positions to Python as comma separated strings.
JN_CSV="$(IFS=,; echo "${ARM_JOINTS[*]}")"
PJ_CSV="$(IFS=,; echo "${PACKED_JOINTS[*]}")"

ARM_ACTION="$JTC_ACTION" \
ARM_JOINTS_CSV="$JN_CSV" \
PACKED_JOINTS_CSV="$PJ_CSV" \
ARM_TIME="$ARM_TIME" \
GOAL_TIMEOUT="$GOAL_TIMEOUT" \
python3 - <<'PY'
import os, sys, time
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration

action   = os.environ["ARM_ACTION"]
joints   = [s.strip() for s in os.environ["ARM_JOINTS_CSV"].split(",") if s.strip()]
targets  = [float(s) for s in os.environ["PACKED_JOINTS_CSV"].split(",") if s.strip()]
arm_time = float(os.environ["ARM_TIME"])
goal_to  = float(os.environ["GOAL_TIMEOUT"])

if len(joints) != 6 or len(targets) != 6:
    print(f"ERROR: need 6 joints/6 values, got {len(joints)}/{len(targets)}", file=sys.stderr)
    sys.exit(2)

def to_dur(s):
    sec = int(s); return Duration(sec=sec, nanosec=int(round((s-sec)*1e9)))

rclpy.init()
node = Node("shutdown_park")
cli = ActionClient(node, FollowJointTrajectory, action)
print(f"[shutdown] waiting for action server {action} ...", flush=True)
if not cli.wait_for_server(timeout_sec=15.0):
    print("ERROR: action server not reachable - is the JTC running?", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)

traj = JointTrajectory()
traj.joint_names = joints
traj.points = [JointTrajectoryPoint(positions=targets, time_from_start=to_dur(arm_time))]
goal = FollowJointTrajectory.Goal(); goal.trajectory = traj
print(f"[shutdown] sending trajectory to packed (travel time {arm_time}s)", flush=True)

gh = cli.send_goal_async(goal)
rclpy.spin_until_future_complete(node, gh, timeout_sec=15.0)
if gh.result() is None or not gh.result().accepted:
    print("ERROR: trajectory goal rejected (arm in trajectory mode? protective stop?)", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)

rf = gh.result().get_result_async()
rclpy.spin_until_future_complete(node, rf, timeout_sec=goal_to + 15.0)
res = rf.result()
if res is None:
    print(f"ERROR: no result within {goal_to}s", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)
ec = res.result.error_code
if ec == FollowJointTrajectory.Result.SUCCESSFUL:
    print(f"[shutdown] arm in packed (error_code={ec})", flush=True)
    ok = 0
else:
    print(f"ERROR: trajectory not successful (error_code={ec})", file=sys.stderr)
    ok = 1
node.destroy_node(); rclpy.shutdown(); sys.exit(ok)
PY
PARK_RC=$?
if [ "$PARK_RC" -ne 0 ]; then
  die "parking the arm failed (rc=${PARK_RC}) - shutdown ABORTED, the robot stays on."
fi

# ---------------------------------------------------------------------------
# 4. power the arm down
# ---------------------------------------------------------------------------
log "step 4/6: powering the arm down (ur_state_manager/power_off)"
call_trigger "$POWER_OFF_SRV" "power_off" 30.0 || warn "power_off not successful - the brakes engage mechanically anyway."

# ---------------------------------------------------------------------------
# 5. stop the platform services
# ---------------------------------------------------------------------------
if [ "$DO_SERVICES" -eq 1 ]; then
  log "step 5/6: stopping the platform services (clearpath-manipulators, clearpath-robot)"
  for u in clearpath-manipulators.service clearpath-robot.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${u}"; then
      run sudo systemctl stop "$u" || warn "stop ${u} failed"
    else
      warn "unit ${u} not installed - skipped"
    fi
  done
else
  log "step 5/6: skipped (--no-services)"
fi

# ---------------------------------------------------------------------------
# 6. switch the robot PC off
# ---------------------------------------------------------------------------
if [ "$DO_POWEROFF" -eq 1 ]; then
  log "step 6/6: switching the robot PC off (systemctl poweroff)"
  if [ "$DO_YES" -ne 1 ]; then
    echo "  The robot PC will be shut down and switched off." >&2
    printf '  Continue? [y/N] ' >&2
    read -r ans
    case "$ans" in
      j|J|y|Y) : ;;
      *) warn "aborted - services are stopped, the PC stays on."; exit 0 ;;
    esac
  fi
  run sudo systemctl poweroff
else
  log "step 6/6: skipped (--no-poweroff) - the PC stays on."
  log "shutdown: arm parked + powered down, services stopped. See you tomorrow."
fi