#!/usr/bin/env bash
# wakeup.sh - counterpart to shutdown.sh: drive the robot arm out of the
#             rest pose "packed" back into the working pose ("home", by
#             default from robot.yaml).
#
# Runs DIRECTLY on the robot PC (a200-0553) against the local ROS 2 graph.
# Sequence:
#   1. make the arm ready              (ur_state_manager/prepare - power on +
#                                       release brakes; idempotent)
#   2. switch to trajectory mode       (ur_controller_mode_manager/mode/trajectory,
#                                       so that the JTC accepts the goal)
#   3. resolve the target pose         (robot.yaml -> poses[name].joints)
#   4. check the start pose            (the arm should stand in "packed";
#                                       otherwise the joint interpolation is
#                                       not collision checked)
#   5. drive the arm to the target     (arm_0_joint_trajectory_controller)
#   6. power the arm down              (ur_state_manager/power_off) - ONLY with
#                                       --power-off-arm
#
# NOTHING is started and nothing is shut down - the platform services must
# already be running (boot services from husky-custom-setup). The arm stays
# powered and in trajectory mode at the end, so it is ready for MoveIt;
# --power-off-arm de-energises it instead, so the arm stands in the target pose
# on its brakes and has to be prepared again before the next movement.
#
# The arm moves widely and fast -> there is a confirmation before the travel
# (skippable with -y / --yes).
#
# Options:
#   -y, --yes           no confirmation before the arm moves
#   --pose <name>       target pose from robot.yaml (default: home, fallback forward)
#   --joints <csv>      target pose directly as 6 joint angles in rad, comma separated
#                       (overrides --pose)
#   --from-any          do NOT check the start pose against "packed"
#   --power-off-arm     power the arm down after the travel (ur_state_manager/power_off);
#                       the arm holds the target pose on its brakes
#   --time <sec>        travel time (default 10.0)
#   --ns <namespace>    robot namespace (default: a200_0553 or $CLEARPATH_NS)
#   -h, --help          this help
#
# Env:
#   CLEARPATH_NS        robot namespace (default a200_0553)
#   ROBOT_YAML          path to robot.yaml (default: search, see below)
#   WAKEUP_ARM_TIME     travel time in s (default 10.0 - a large movement)
#   WAKEUP_GOAL_TIMEOUT max wait for the trajectory result in s (default 60)
#   WAKEUP_TOL          tolerance of the start pose check in rad (default 0.35)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
NS="${CLEARPATH_NS:-a200_0553}"
MANIP_NS="${NS}/manipulators"
ARM_TIME="${WAKEUP_ARM_TIME:-10.0}"
GOAL_TIMEOUT="${WAKEUP_GOAL_TIMEOUT:-60}"
START_TOL="${WAKEUP_TOL:-0.35}"

POSE_NAME="home"
POSE_FALLBACKS="forward"     # tried when POSE_NAME is not in robot.yaml
JOINTS_CSV=""                # via --joints; empty -> resolve from robot.yaml

# Expected start pose = "packed" from robot.yaml (identical to shutdown.sh).
# Only for the sanity check, not as a travel target.
PACKED_JOINTS=(
  -0.000695530568258107
  -3.1283000151263636
   2.8355469703674316
  -3.193974320088522
   1.5455983877182007
  -0.0000837484928349762
)
# Fallback target pose if robot.yaml is not found/readable: "forward".
FORWARD_JOINTS=(
  -0.00532704988588506
  -2.2551897207843226
   2.246230125427246
  -3.1489999930011194
  -1.569127384816305
  -0.00013143221010381012
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
CHECK_START=1
DO_POWER_OFF=0
TOTAL_STEPS=5

# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------
usage() { sed -n '2,47p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        DO_YES=1; shift ;;
    --pose)          POSE_NAME="$2"; shift 2 ;;
    --joints)        JOINTS_CSV="$2"; shift 2 ;;
    --from-any)      CHECK_START=0; shift ;;
    --power-off-arm) DO_POWER_OFF=1; TOTAL_STEPS=6; shift ;;
    --time)          ARM_TIME="$2"; shift 2 ;;
    --ns)            NS="$2"; MANIP_NS="${NS}/manipulators"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "wakeup: unknown option: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { printf '\033[1;32m[wakeup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[wakeup]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[wakeup]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# ROS environment
# ---------------------------------------------------------------------------
# The canonical entry point is /etc/clearpath/setup.bash: it sources the
# jazzy setup, onrobot-rg6 and - DECISIVELY - sets ROS_DOMAIN_ID and
# RMW_IMPLEMENTATION (rmw_zenoh_cpp). Without the latter the script runs in
# the ROS jazzy default (FastDDS) and is NOT in the same graph as the robot
# stacks -> ros2 service call hangs. So try it BEFORE the bare
# /opt/ros path. ROS setup scripts touch variables that are unbound under
# `set -u` (e.g. AMENT_TRACE_SETUP_FILES) -> turn -u off while sourcing.
if [ -f /etc/clearpath/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /etc/clearpath/setup.bash; set -u
elif [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /opt/ros/jazzy/setup.bash; set -u
  : "${ROS_DOMAIN_ID:=0}";        export ROS_DOMAIN_ID
  : "${RMW_IMPLEMENTATION:=rmw_zenoh_cpp}"; export RMW_IMPLEMENTATION
else
  die "/etc/clearpath/setup.bash and /opt/ros/jazzy/setup.bash are missing - is wakeup.sh running on the robot PC?"
fi
for ws in /opt/ros/clearpath/setup.bash /opt/ros/robot/setup.bash \
          /home/robot/ros2_ws/install/setup.bash /ros2_ws/install/setup.bash; do
  [ -f "$ws" ] && { # shellcheck disable=SC1091
    set +u; source "$ws" || true; set -u; }
done

JTC_ACTION="/${MANIP_NS}/arm_0_joint_trajectory_controller/follow_joint_trajectory"
JTC_STATE="/${MANIP_NS}/arm_0_joint_trajectory_controller/controller_state"
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
# 1. resolve the target pose (robot.yaml is the source of truth)
# ---------------------------------------------------------------------------
log "step 1/${TOTAL_STEPS}: resolving target pose '${POSE_NAME}'"

if [ -n "$JOINTS_CSV" ]; then
  log "target pose taken from --joints"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # Search order: explicitly set -> installed Clearpath config -> checkout next
  # to this script -> home of the robot user.
  YAML_CANDIDATES=(
    "${ROBOT_YAML:-}"
    /etc/clearpath/robot.yaml
    "${SCRIPT_DIR}/../robot.yaml"
    "${SCRIPT_DIR}/robot.yaml"
    "${HOME:-/home/robot}/robot.yaml"
    "${HOME:-/home/robot}/husky-custom-setup/robot.yaml"
  )
  for cand in "${YAML_CANDIDATES[@]}"; do
    [ -n "$cand" ] && [ -r "$cand" ] || continue
    JOINTS_CSV="$(POSE_NAME="$POSE_NAME" POSE_FALLBACKS="$POSE_FALLBACKS" \
                  ROBOT_YAML_PATH="$cand" python3 - <<'PY' || true
import os, sys, yaml

path  = os.environ["ROBOT_YAML_PATH"]
names = [os.environ["POSE_NAME"]] + \
        [n for n in os.environ.get("POSE_FALLBACKS", "").split(",") if n.strip()]

try:
    with open(path) as fh:
        cfg = yaml.safe_load(fh) or {}
except Exception as exc:                       # broken/unreadable YAML -> next candidate
    print(f"wakeup: {path} not readable: {exc}", file=sys.stderr)
    sys.exit(1)

poses = {}
for arm in (cfg.get("manipulators") or {}).get("arms") or []:
    for pose in arm.get("poses") or []:
        if pose.get("name") and pose.get("joints"):
            poses.setdefault(pose["name"], pose["joints"])

for name in names:
    j = poses.get(name.strip())
    if j and len(j) == 6:
        # stderr = diagnosis for the operator, stdout = the plain result for bash
        print(f"wakeup: pose '{name.strip()}' from {path}", file=sys.stderr)
        print(",".join(repr(float(v)) for v in j))
        sys.exit(0)

print(f"wakeup: none of the poses {names} in {path} "
      f"(present: {sorted(poses)})", file=sys.stderr)
sys.exit(1)
PY
                  )"
    [ -n "$JOINTS_CSV" ] && break
  done
fi

if [ -z "$JOINTS_CSV" ]; then
  warn "target pose not resolvable from robot.yaml - using the built-in pose 'forward'."
  JOINTS_CSV="$(IFS=,; echo "${FORWARD_JOINTS[*]}")"
fi
log "target joint angles: ${JOINTS_CSV}"

# ---------------------------------------------------------------------------
# 2. make the arm ready (idempotent: power on + release brakes)
# ---------------------------------------------------------------------------
log "step 2/${TOTAL_STEPS}: preparing the arm (ur_state_manager/prepare)"
call_trigger "$PREPARE_SRV" "prepare" 30.0 \
  || die "prepare failed - arm not powered/unbraked. Aborting, nothing is driven."

# ---------------------------------------------------------------------------
# 3. activate trajectory mode (otherwise the JTC rejects the goal)
# ---------------------------------------------------------------------------
log "step 3/${TOTAL_STEPS}: activating trajectory mode (mode/trajectory)"
call_trigger "$TRAJ_MODE_SRV" "mode/trajectory" 15.0 \
  || warn "mode/trajectory not successful - attempting the movement anyway."

# ---------------------------------------------------------------------------
# 4. confirmation - from here on the arm makes a large movement
# ---------------------------------------------------------------------------
if [ "$DO_YES" -ne 1 ]; then
  echo "  The arm now travels from 'packed' to '${POSE_NAME}' (${ARM_TIME}s)." >&2
  [ "$DO_POWER_OFF" -eq 1 ] && \
    echo "  Afterwards it is powered DOWN (--power-off-arm) and holds on its brakes." >&2
  echo "  Workspace clear? Nobody inside the swivel range?" >&2
  printf '  Continue? [y/N] ' >&2
  read -r ans
  case "$ans" in
    j|J|y|Y) : ;;
    *) warn "aborted - the arm is powered and in trajectory mode, but stands still."; exit 0 ;;
  esac
fi

# ---------------------------------------------------------------------------
# 5. check the start pose + drive the arm to the target pose
# ---------------------------------------------------------------------------
log "step 4/${TOTAL_STEPS}: checking the start pose (expects 'packed', tolerance ${START_TOL} rad)"
log "step 5/${TOTAL_STEPS}: driving the arm to '${POSE_NAME}' (${ARM_TIME}s)"

JN_CSV="$(IFS=,; echo "${ARM_JOINTS[*]}")"
PK_CSV="$(IFS=,; echo "${PACKED_JOINTS[*]}")"

ARM_ACTION="$JTC_ACTION" \
ARM_STATE_TOPIC="$JTC_STATE" \
ARM_JOINTS_CSV="$JN_CSV" \
TARGET_JOINTS_CSV="$JOINTS_CSV" \
PACKED_JOINTS_CSV="$PK_CSV" \
ARM_TIME="$ARM_TIME" \
GOAL_TIMEOUT="$GOAL_TIMEOUT" \
START_TOL="$START_TOL" \
CHECK_START="$CHECK_START" \
POSE_NAME="$POSE_NAME" \
python3 - <<'PY'
import os, sys
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTrajectoryControllerState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from builtin_interfaces.msg import Duration

action    = os.environ["ARM_ACTION"]
state_top = os.environ["ARM_STATE_TOPIC"]
joints    = [s.strip() for s in os.environ["ARM_JOINTS_CSV"].split(",") if s.strip()]
targets   = [float(s) for s in os.environ["TARGET_JOINTS_CSV"].split(",") if s.strip()]
packed    = [float(s) for s in os.environ["PACKED_JOINTS_CSV"].split(",") if s.strip()]
arm_time  = float(os.environ["ARM_TIME"])
goal_to   = float(os.environ["GOAL_TIMEOUT"])
tol       = float(os.environ["START_TOL"])
check     = os.environ["CHECK_START"] == "1"
pose_name = os.environ["POSE_NAME"]

if len(joints) != 6 or len(targets) != 6:
    print(f"ERROR: need 6 joints/6 values, got {len(joints)}/{len(targets)}", file=sys.stderr)
    sys.exit(2)

def to_dur(s):
    sec = int(s); return Duration(sec=sec, nanosec=int(round((s-sec)*1e9)))

def fail(node, msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(code)

rclpy.init()
node = Node("wakeup_move")

# --- read the start pose (advisory): the JTC publishes its actual state.
# Pure diagnosis - if it fails, only a warning is issued, because the operator
# has already confirmed the movement.
latest = {}
def on_state(msg):
    pt = getattr(msg, "actual", None) or getattr(msg, "feedback", None)
    if pt is not None and pt.positions:
        latest["names"] = list(msg.joint_names)
        latest["pos"]   = list(pt.positions)

node.create_subscription(JointTrajectoryControllerState, state_top, on_state, 10)
deadline = node.get_clock().now().nanoseconds + int(5e9)
while not latest and node.get_clock().now().nanoseconds < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)

if not latest:
    print(f"WARNING: no actual pose on {state_top} - start pose unchecked.", file=sys.stderr)
else:
    idx = {n: i for i, n in enumerate(latest["names"])}
    cur = [latest["pos"][idx[n]] if n in idx else float("nan") for n in joints]
    print("[wakeup] actual pose: " + ", ".join(f"{v:+.3f}" for v in cur), flush=True)
    dev = [abs(c - p) for c, p in zip(cur, packed)]
    worst = max(dev)
    if worst > tol:
        bad = ", ".join(f"{joints[i]}={dev[i]:.2f}" for i in range(6) if dev[i] > tol)
        msg = (f"the arm does not stand in 'packed' (deviation up to {worst:.2f} rad: {bad}). "
               f"The travel is a pure joint interpolation and is therefore only "
               f"collision checked when starting from 'packed'.")
        if check:
            fail(node, msg + " Use --from-any to drive anyway.")
        print(f"WARNING: {msg} (--from-any set, driving anyway)", file=sys.stderr)
    else:
        print(f"[wakeup] start pose ok (max deviation {worst:.3f} rad)", flush=True)

# --- travel
cli = ActionClient(node, FollowJointTrajectory, action)
print(f"[wakeup] waiting for action server {action} ...", flush=True)
if not cli.wait_for_server(timeout_sec=15.0):
    fail(node, "action server not reachable - is the JTC running?")

traj = JointTrajectory()
traj.joint_names = joints
traj.points = [JointTrajectoryPoint(positions=targets, time_from_start=to_dur(arm_time))]
goal = FollowJointTrajectory.Goal(); goal.trajectory = traj
print(f"[wakeup] sending trajectory to {pose_name} (travel time {arm_time}s)", flush=True)

gh = cli.send_goal_async(goal)
rclpy.spin_until_future_complete(node, gh, timeout_sec=15.0)
if gh.result() is None or not gh.result().accepted:
    fail(node, "trajectory goal rejected (arm in trajectory mode? protective stop?)")

rf = gh.result().get_result_async()
rclpy.spin_until_future_complete(node, rf, timeout_sec=goal_to + 15.0)
res = rf.result()
if res is None:
    fail(node, f"no result within {goal_to}s")
ec = res.result.error_code
if ec == FollowJointTrajectory.Result.SUCCESSFUL:
    print(f"[wakeup] arm in {pose_name} (error_code={ec})", flush=True)
    ok = 0
else:
    print(f"ERROR: trajectory not successful (error_code={ec})", file=sys.stderr)
    ok = 1
node.destroy_node(); rclpy.shutdown(); sys.exit(ok)
PY
MOVE_RC=$?
if [ "$MOVE_RC" -ne 0 ]; then
  die "travel to '${POSE_NAME}' failed (rc=${MOVE_RC}) - the arm stays put, powered."
fi

# ---------------------------------------------------------------------------
# 6. power the arm down (only with --power-off-arm)
# ---------------------------------------------------------------------------
if [ "$DO_POWER_OFF" -eq 1 ]; then
  log "step 6/6: powering the arm down (ur_state_manager/power_off)"
  # shutdown.sh only WARNS here because the PC poweroff follows and de-energises
  # the arm anyway. Nothing follows here: a failed power_off leaves the arm
  # energised, the opposite of what was asked for - hence an error.
  call_trigger "$POWER_OFF_SRV" "power_off" 30.0 \
    || die "power_off failed - the arm stands in '${POSE_NAME}' but is STILL ENERGISED."
  log "wakeup: the arm stands in '${POSE_NAME}', powered down and holding on its brakes."
  log "wakeup: prepare + mode/trajectory are needed again before the next movement."
else
  log "wakeup: the arm stands in '${POSE_NAME}', powered and in trajectory mode (ready for MoveIt)."
fi
