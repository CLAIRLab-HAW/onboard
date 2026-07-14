#!/usr/bin/env bash
# feierabend.sh - Roboterarm in die Pose "packed" fahren und die Anlage
#                 kontrolliert herunterfahren.
#
# Laeuft DIREKT auf dem Roboter-PC (a200-0553) gegen den lokalen ROS-2-Graph.
# Ablauf:
#   1. Arm einsatzbereit machen        (ur_state_manager/prepare, idempotent)
#   2. auf Trajectory-Modus schalten   (ur_controller_mode_manager/mode/trajectory,
#                                       damit der JTC den Goal annimmt)
#   3. Arm auf Pose "packed" fahren    (arm_0_joint_trajectory_controller,
#                                       absolute Gelenkwinkel aus robot.yaml)
#   4. Arm stromlos schalten           (ur_state_manager/power_off)
#   5. Plattform-Services stoppen      (clearpath-manipulators + clearpath-robot)
#   6. Roboter-PC ausschalten          (systemctl poweroff)
#
# Schritte 5+6 brauchen root (sudo). Schritt 6 ist der irreparable Teil - er
# schaltet den ganzen Roboter-PC aus; deshalb gibt es davor eine Bestaetigung
# (ueberspringbar mit -y / --yes).
#
# Optionen:
#   -y, --yes           keine Rueckfrage vor poweroff
#   --no-poweroff       KEIN systemctl poweroff (nur Services stoppen, PC anlassen)
#   --no-services       Plattform-Services NICHT stoppen (nur Arm parken + power_off)
#   --ns <namespace>    Roboter-Namespace (Default: a200_0553 bzw. $CLEARPATH_NS)
#   -h, --help          diese Hilfe
#
# Env:
#   CLEARPATH_NS            Roboter-Namespace (Default a200_0553)
#   FEIERABEND_ARM_TIME     Fahrzeit nach packed in s (Default 10.0 - grosse Bewegung)
#   FEIERABEND_GOAL_TIMEOUT Max. Warten auf Trajectory-Ergebnis in s (Default 60)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
NS="${CLEARPATH_NS:-a200_0553}"
MANIP_NS="${NS}/manipulators"
ARM_TIME="${FEIERABEND_ARM_TIME:-10.0}"
GOAL_TIMEOUT="${FEIERABEND_GOAL_TIMEOUT:-60}"

# Pose "packed" aus husky-custom-setup/robot.yaml (UR-Kanonische Reihenfolge:
# shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3). Bei Aenderung
# in robot.yaml hier synchron halten (oder den generate_semantic_description-
# Pfad nutzen und per MoveIt-Group-State fahren).
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
# Argumente
# ---------------------------------------------------------------------------
usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        DO_YES=1; shift ;;
    --no-poweroff)   DO_POWEROFF=0; shift ;;
    --no-services)   DO_SERVICES=0; shift ;;
    --ns)            NS="$2"; MANIP_NS="${NS}/manipulators"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "feierabend: unbekannte Option: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m[feierabend]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[feierabend]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[feierabend]\033[0m %s\n' "$*" >&2; exit 1; }

run() { log "$*"; "$@"; }

# ---------------------------------------------------------------------------
# ROS-Umgebung
# ---------------------------------------------------------------------------
# Kanonischer Einstieg ist /etc/clearpath/setup.bash: sie sourct das
# Jazzy-Setup, onrobot-rg6 und - ENTSCHEIDEND - setzt ROS_DOMAIN_ID und
# RMW_IMPLEMENTATION (rmw_zenoh_cpp). Ohne letzteres laeuft feierabend im
# ROS-Jazzy-Default (FastDDS) und ist NICHT im selben Graph wie die
# Roboter-Stacks -> ros2 service call haengt ("waiting for service to
# become available"). Daher VOR dem nackten /opt/ros-Pfad probieren.
# ROS-Setup-Scripts fassen Variablen an, die unter `set -u` ungebunden
# sind (z.B. AMENT_TRACE_SETUP_FILES) -> waehrend des Sourcens -u aus.
if [ -f /etc/clearpath/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /etc/clearpath/setup.bash; set -u
elif [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /opt/ros/jazzy/setup.bash; set -u
  # Fallback auf Nicht-Clearpath-Boxen: zumindest Default-Domain + die
  # auf Clearpath-Robotern uebliche RMW (zenoh) setzen, falls nicht gesetzt.
  : "${ROS_DOMAIN_ID:=0}";        export ROS_DOMAIN_ID
  : "${RMW_IMPLEMENTATION:=rmw_zenoh_cpp}"; export RMW_IMPLEMENTATION
else
  die "/etc/clearpath/setup.bash und /opt/ros/jazzy/setup.bash fehlen - feierabend.sh laeuft auf dem Roboter-PC?"
fi
# Falls es ein lokales Workspace-Setup gibt, zusätzlich sourcen (ohne Fehler).
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
# ROS-Service-Helfer: ruft einen std_srvs/Trigger auf und wertet success aus.
# ---------------------------------------------------------------------------
call_trigger() {
  # std_srvs/Trigger hat einen LEEREN Request (nur bool success + string message
  # auf der Response) - kein Feld uebergeben. ros2 kennt kein `service wait`,
  # darum harten Timeout außenrum (Service nicht da -> ros2 service call wuerde
  # sonst haengen).
  local srv="$1" label="$2" timeout="${3:-30}"
  local secs="${timeout%.*}"   # Float -> Int (z.B. 30.0 -> 30) fuer Bash-Arithmetik
  [ -z "$secs" ] && secs="$timeout"
  log "${label}: rufe ${srv}"
  local out rc
  out="$(timeout "$((secs + 15))" ros2 service call "$srv" std_srvs/srv/Trigger 2>&1 || true)"
  rc=$?
  if [ "$rc" -eq 124 ]; then
    warn "${label}: Timeout - Service ${srv} nicht erreichbar."
    return 1
  fi
  echo "$out" | grep -qiE 'success:\s*true' && { log "${label}: ok"; return 0; }
  warn "${label}: kein success=true. Auszug:"
  echo "$out" | tail -n 6 | sed 's/^/    /' >&2
  return 1
}

# ---------------------------------------------------------------------------
# 1. Arm einsatzbereit (idempotent)
# ---------------------------------------------------------------------------
log "Schritt 1/6: Arm vorbereiten (ur_state_manager/prepare)"
call_trigger "$PREPARE_SRV" "prepare" 30.0 || warn "prepare nicht erfolgreich - weiter im Versuch."

# ---------------------------------------------------------------------------
# 2. Trajectory-Modus aktivieren (sonst lehnt der JTC den Goal ab)
# ---------------------------------------------------------------------------
log "Schritt 2/6: Trajectory-Modus aktivieren (mode/trajectory)"
call_trigger "$TRAJ_MODE_SRV" "mode/trajectory" 15.0 || warn "mode/trajectory nicht erfolgreich - versuche Bewegung trotzdem."

# ---------------------------------------------------------------------------
# 3. Arm auf "packed" fahren (absolute Trajectory ueber den JTC)
# ---------------------------------------------------------------------------
log "Schritt 3/6: Arm auf Pose 'packed' fahren (${ARM_TIME}s)"

# joint_names + positions als kommaseparierte Strings fuer Python uebergeben.
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
    print(f"FEHLER: brauche 6 Joints/6 Werte, got {len(joints)}/{len(targets)}", file=sys.stderr)
    sys.exit(2)

def to_dur(s):
    sec = int(s); return Duration(sec=sec, nanosec=int(round((s-sec)*1e9)))

rclpy.init()
node = Node("feierabend_park")
cli = ActionClient(node, FollowJointTrajectory, action)
print(f"[feierabend] warte auf Action-Server {action} ...", flush=True)
if not cli.wait_for_server(timeout_sec=15.0):
    print("FEHLER: Action-Server nicht erreichbar - laeuft der JTC?", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)

traj = JointTrajectory()
traj.joint_names = joints
traj.points = [JointTrajectoryPoint(positions=targets, time_from_start=to_dur(arm_time))]
goal = FollowJointTrajectory.Goal(); goal.trajectory = traj
print(f"[feierabend] sende Trajectory nach packed (Fahrzeit {arm_time}s)", flush=True)

gh = cli.send_goal_async(goal)
rclpy.spin_until_future_complete(node, gh, timeout_sec=15.0)
if gh.result() is None or not gh.result().accepted:
    print("FEHLER: Trajectory-Goal abgelehnt (Arm in trajectory-Modus? Schutzstop?)", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)

rf = gh.result().get_result_async()
rclpy.spin_until_future_complete(node, rf, timeout_sec=goal_to + 15.0)
res = rf.result()
if res is None:
    print(f"FEHLER: kein Ergebnis innerhalb {goal_to}s", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(1)
ec = res.result.error_code
if ec == FollowJointTrajectory.Result.SUCCESSFUL:
    print(f"[feierabend] Arm in packed (error_code={ec})", flush=True)
    ok = 0
else:
    print(f"FEHLER: Trajectory nicht erfolgreich (error_code={ec})", file=sys.stderr)
    ok = 1
node.destroy_node(); rclpy.shutdown(); sys.exit(ok)
PY
PARK_RC=$?
if [ "$PARK_RC" -ne 0 ]; then
  die "Arm-Parken fehlgeschlagen (rc=${PARK_RC}) - Shutdown ABGEBROCHEN, Roboter bleibt an."
fi

# ---------------------------------------------------------------------------
# 4. Arm stromlos
# ---------------------------------------------------------------------------
log "Schritt 4/6: Arm stromlos schalten (ur_state_manager/power_off)"
call_trigger "$POWER_OFF_SRV" "power_off" 30.0 || warn "power_off nicht erfolgreich - Bremsen greifen mechanisch trotzdem."

# ---------------------------------------------------------------------------
# 5. Plattform-Services stoppen
# ---------------------------------------------------------------------------
if [ "$DO_SERVICES" -eq 1 ]; then
  log "Schritt 5/6: Plattform-Services stoppen (clearpath-manipulators, clearpath-robot)"
  for u in clearpath-manipulators.service clearpath-robot.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${u}"; then
      run sudo systemctl stop "$u" || warn "stop ${u} fehlgeschlagen"
    else
      warn "Unit ${u} nicht installiert - uebersprungen"
    fi
  done
else
  log "Schritt 5/6: uebersprungen (--no-services)"
fi

# ---------------------------------------------------------------------------
# 6. Roboter-PC ausschalten
# ---------------------------------------------------------------------------
if [ "$DO_POWEROFF" -eq 1 ]; then
  log "Schritt 6/6: Roboter-PC ausschalten (systemctl poweroff)"
  if [ "$DO_YES" -ne 1 ]; then
    echo "  Der Roboter-PC wird heruntergefahren und geht aus." >&2
    printf '  Weiter? [j/N] ' >&2
    read -r ans
    case "$ans" in
      j|J|y|Y) : ;;
      *) warn "Abgebrochen - Services sind gestoppt, PC bleibt an."; exit 0 ;;
    esac
  fi
  run sudo systemctl poweroff
else
  log "Schritt 6/6: uebersprungen (--no-poweroff) - PC bleibt an."
  log "Feierabend: Arm geparkt + stromlos, Services gestoppt. Bis morgen."
fi