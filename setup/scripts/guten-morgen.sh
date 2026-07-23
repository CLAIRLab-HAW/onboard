#!/usr/bin/env bash
# guten-morgen.sh - Gegenstueck zu feierabend.sh: Roboterarm aus der
#                   Feierabend-Pose "packed" zurueck in die Arbeitspose
#                   ("home", per Default aus robot.yaml) fahren.
#
# Laeuft DIREKT auf dem Roboter-PC (a200-0553) gegen den lokalen ROS-2-Graph.
# Ablauf:
#   1. Arm einsatzbereit machen        (ur_state_manager/prepare - Power On +
#                                       Bremsen loesen; idempotent)
#   2. auf Trajectory-Modus schalten   (ur_controller_mode_manager/mode/trajectory,
#                                       damit der JTC den Goal annimmt)
#   3. Zielpose aufloesen              (robot.yaml -> poses[name].joints)
#   4. Startpose pruefen               (Arm sollte in "packed" stehen; sonst ist
#                                       die Gelenk-Interpolation nicht geprueft)
#   5. Arm auf Zielpose fahren         (arm_0_joint_trajectory_controller)
#
# Es wird NICHTS gestartet und nichts abgeschaltet - die Plattform-Services
# muessen bereits laufen (Boot-Services aus husky-custom-setup). Der Arm bleibt
# am Ende bestromt und im Trajectory-Modus, also bereit fuer MoveIt.
#
# Der Arm bewegt sich gross und schnell -> vor der Fahrt gibt es eine
# Bestaetigung (ueberspringbar mit -y / --yes).
#
# Optionen:
#   -y, --yes           keine Rueckfrage vor der Armbewegung
#   --pose <name>       Zielpose aus robot.yaml (Default: home, Fallback forward)
#   --joints <csv>      Zielpose direkt als 6 Gelenkwinkel in rad, kommasepariert
#                       (ueberschreibt --pose)
#   --from-any          Startpose NICHT gegen "packed" pruefen
#   --time <sek>        Fahrzeit (Default 10.0)
#   --ns <namespace>    Roboter-Namespace (Default: a200_0553 bzw. $CLEARPATH_NS)
#   -h, --help          diese Hilfe
#
# Env:
#   CLEARPATH_NS              Roboter-Namespace (Default a200_0553)
#   ROBOT_YAML                Pfad zur robot.yaml (Default: Suche, s.u.)
#   GUTEN_MORGEN_ARM_TIME     Fahrzeit in s (Default 10.0 - grosse Bewegung)
#   GUTEN_MORGEN_GOAL_TIMEOUT Max. Warten auf Trajectory-Ergebnis in s (Default 60)
#   GUTEN_MORGEN_TOL          Toleranz der Startpose-Pruefung in rad (Default 0.35)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
NS="${CLEARPATH_NS:-a200_0553}"
MANIP_NS="${NS}/manipulators"
ARM_TIME="${GUTEN_MORGEN_ARM_TIME:-10.0}"
GOAL_TIMEOUT="${GUTEN_MORGEN_GOAL_TIMEOUT:-60}"
START_TOL="${GUTEN_MORGEN_TOL:-0.35}"

POSE_NAME="home"
POSE_FALLBACKS="forward"     # probiert, wenn POSE_NAME nicht in robot.yaml steht
JOINTS_CSV=""                # via --joints; leer -> aus robot.yaml aufloesen

# Erwartete Startpose = "packed" aus robot.yaml (identisch zu feierabend.sh).
# Nur fuer die Plausibilitaets-Pruefung, nicht als Fahrziel.
PACKED_JOINTS=(
  -0.000695530568258107
  -3.1283000151263636
   2.8355469703674316
  -3.193974320088522
   1.5455983877182007
  -0.0000837484928349762
)
# Fallback-Zielpose, falls robot.yaml nicht gefunden/lesbar ist: "forward".
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

# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------
usage() { sed -n '2,39p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        DO_YES=1; shift ;;
    --pose)          POSE_NAME="$2"; shift 2 ;;
    --joints)        JOINTS_CSV="$2"; shift 2 ;;
    --from-any)      CHECK_START=0; shift ;;
    --time)          ARM_TIME="$2"; shift 2 ;;
    --ns)            NS="$2"; MANIP_NS="${NS}/manipulators"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "guten-morgen: unbekannte Option: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { printf '\033[1;32m[guten-morgen]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[guten-morgen]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[guten-morgen]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# ROS-Umgebung
# ---------------------------------------------------------------------------
# Kanonischer Einstieg ist /etc/clearpath/setup.bash: sie sourct das
# Jazzy-Setup, onrobot-rg6 und - ENTSCHEIDEND - setzt ROS_DOMAIN_ID und
# RMW_IMPLEMENTATION (rmw_zenoh_cpp). Ohne letzteres laeuft das Script im
# ROS-Jazzy-Default (FastDDS) und ist NICHT im selben Graph wie die
# Roboter-Stacks -> ros2 service call haengt. Daher VOR dem nackten
# /opt/ros-Pfad probieren. ROS-Setup-Scripts fassen Variablen an, die unter
# `set -u` ungebunden sind (z.B. AMENT_TRACE_SETUP_FILES) -> beim Sourcen -u aus.
if [ -f /etc/clearpath/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /etc/clearpath/setup.bash; set -u
elif [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  set +u; source /opt/ros/jazzy/setup.bash; set -u
  : "${ROS_DOMAIN_ID:=0}";        export ROS_DOMAIN_ID
  : "${RMW_IMPLEMENTATION:=rmw_zenoh_cpp}"; export RMW_IMPLEMENTATION
else
  die "/etc/clearpath/setup.bash und /opt/ros/jazzy/setup.bash fehlen - guten-morgen.sh laeuft auf dem Roboter-PC?"
fi
for ws in /opt/ros/clearpath/setup.bash /opt/ros/robot/setup.bash \
          /home/robot/ros2_ws/install/setup.bash /ros2_ws/install/setup.bash; do
  [ -f "$ws" ] && { # shellcheck disable=SC1091
    set +u; source "$ws" || true; set -u; }
done

JTC_ACTION="/${MANIP_NS}/arm_0_joint_trajectory_controller/follow_joint_trajectory"
JTC_STATE="/${MANIP_NS}/arm_0_joint_trajectory_controller/controller_state"
PREPARE_SRV="/${MANIP_NS}/ur_state_manager/prepare"
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
  # Exit-Code des timeouts DIREKT via `|| rc=$?` einfangen - NICHT `|| true`
  # in die Substitution und danach `rc=$?`: das liest den Status der
  # Zuweisung (immer 0), der 124-Zweig waere tot.
  local out rc=0
  out="$(timeout "$((secs + 15))" ros2 service call "$srv" std_srvs/srv/Trigger 2>&1)" || rc=$?
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
# 1. Zielpose aufloesen (robot.yaml ist die Quelle der Wahrheit)
# ---------------------------------------------------------------------------
log "Schritt 1/5: Zielpose '${POSE_NAME}' aufloesen"

if [ -n "$JOINTS_CSV" ]; then
  log "Zielpose aus --joints uebernommen"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # Suchreihenfolge: explizit gesetzt -> installierte Clearpath-Config ->
  # Checkout neben diesem Script -> Home des robot-Users.
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
except Exception as exc:                       # kaputte/unlesbare YAML -> naechster Kandidat
    print(f"guten-morgen: {path} nicht lesbar: {exc}", file=sys.stderr)
    sys.exit(1)

poses = {}
for arm in (cfg.get("manipulators") or {}).get("arms") or []:
    for pose in arm.get("poses") or []:
        if pose.get("name") and pose.get("joints"):
            poses.setdefault(pose["name"], pose["joints"])

for name in names:
    j = poses.get(name.strip())
    if j and len(j) == 6:
        # stderr = Diagnose fuer den Bediener, stdout = reines Ergebnis fuer bash
        print(f"guten-morgen: Pose '{name.strip()}' aus {path}", file=sys.stderr)
        print(",".join(repr(float(v)) for v in j))
        sys.exit(0)

print(f"guten-morgen: keine der Posen {names} in {path} "
      f"(vorhanden: {sorted(poses)})", file=sys.stderr)
sys.exit(1)
PY
                  )"
    [ -n "$JOINTS_CSV" ] && { ROBOT_YAML_USED="$cand"; break; }
  done
fi

if [ -z "$JOINTS_CSV" ]; then
  warn "Zielpose nicht aus robot.yaml aufloesbar - nutze eingebaute Pose 'forward'."
  JOINTS_CSV="$(IFS=,; echo "${FORWARD_JOINTS[*]}")"
fi
log "Ziel-Gelenkwinkel: ${JOINTS_CSV}"

# ---------------------------------------------------------------------------
# 2. Arm einsatzbereit (idempotent: Power On + Bremsen loesen)
# ---------------------------------------------------------------------------
log "Schritt 2/5: Arm vorbereiten (ur_state_manager/prepare)"
call_trigger "$PREPARE_SRV" "prepare" 30.0 \
  || die "prepare fehlgeschlagen - Arm nicht bestromt/entbremst. Abbruch, es wird nicht gefahren."

# ---------------------------------------------------------------------------
# 3. Trajectory-Modus aktivieren (sonst lehnt der JTC den Goal ab)
# ---------------------------------------------------------------------------
log "Schritt 3/5: Trajectory-Modus aktivieren (mode/trajectory)"
call_trigger "$TRAJ_MODE_SRV" "mode/trajectory" 15.0 \
  || warn "mode/trajectory nicht erfolgreich - versuche Bewegung trotzdem."

# ---------------------------------------------------------------------------
# 4. Bestaetigung - ab hier bewegt sich der Arm gross
# ---------------------------------------------------------------------------
if [ "$DO_YES" -ne 1 ]; then
  echo "  Der Arm faehrt jetzt von 'packed' nach '${POSE_NAME}' (${ARM_TIME}s)." >&2
  echo "  Arbeitsraum frei? Niemand im Schwenkbereich?" >&2
  printf '  Weiter? [j/N] ' >&2
  read -r ans
  case "$ans" in
    j|J|y|Y) : ;;
    *) warn "Abgebrochen - Arm ist bestromt und im Trajectory-Modus, steht aber still."; exit 0 ;;
  esac
fi

# ---------------------------------------------------------------------------
# 5. Startpose pruefen + Arm auf Zielpose fahren
# ---------------------------------------------------------------------------
log "Schritt 4/5: Startpose pruefen (erwartet 'packed', Toleranz ${START_TOL} rad)"
log "Schritt 5/5: Arm nach '${POSE_NAME}' fahren (${ARM_TIME}s)"

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
    print(f"FEHLER: brauche 6 Joints/6 Werte, got {len(joints)}/{len(targets)}", file=sys.stderr)
    sys.exit(2)

def to_dur(s):
    sec = int(s); return Duration(sec=sec, nanosec=int(round((s-sec)*1e9)))

def fail(node, msg, code=1):
    print(f"FEHLER: {msg}", file=sys.stderr)
    node.destroy_node(); rclpy.shutdown(); sys.exit(code)

rclpy.init()
node = Node("guten_morgen_move")

# --- Startpose lesen (advisory): der JTC veroeffentlicht seinen Ist-Zustand.
# Reine Diagnose - schlaegt sie fehl, wird nur gewarnt, denn die Bewegung ist
# vom Bediener bereits bestaetigt worden.
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
    print(f"WARNUNG: keine Ist-Pose auf {state_top} - Startpose ungeprueft.", file=sys.stderr)
else:
    idx = {n: i for i, n in enumerate(latest["names"])}
    cur = [latest["pos"][idx[n]] if n in idx else float("nan") for n in joints]
    print("[guten-morgen] Ist-Pose: " + ", ".join(f"{v:+.3f}" for v in cur), flush=True)
    dev = [abs(c - p) for c, p in zip(cur, packed)]
    worst = max(dev)
    if worst > tol:
        bad = ", ".join(f"{joints[i]}={dev[i]:.2f}" for i in range(6) if dev[i] > tol)
        msg = (f"Arm steht nicht in 'packed' (Abweichung bis {worst:.2f} rad: {bad}). "
               f"Die Fahrt ist eine reine Gelenk-Interpolation und daher nur aus "
               f"'packed' heraus kollisionsgeprueft.")
        if check:
            fail(node, msg + " Mit --from-any trotzdem fahren.")
        print(f"WARNUNG: {msg} (--from-any gesetzt, fahre trotzdem)", file=sys.stderr)
    else:
        print(f"[guten-morgen] Startpose ok (max. Abweichung {worst:.3f} rad)", flush=True)

# --- Fahrt
cli = ActionClient(node, FollowJointTrajectory, action)
print(f"[guten-morgen] warte auf Action-Server {action} ...", flush=True)
if not cli.wait_for_server(timeout_sec=15.0):
    fail(node, "Action-Server nicht erreichbar - laeuft der JTC?")

traj = JointTrajectory()
traj.joint_names = joints
traj.points = [JointTrajectoryPoint(positions=targets, time_from_start=to_dur(arm_time))]
goal = FollowJointTrajectory.Goal(); goal.trajectory = traj
print(f"[guten-morgen] sende Trajectory nach {pose_name} (Fahrzeit {arm_time}s)", flush=True)

gh = cli.send_goal_async(goal)
rclpy.spin_until_future_complete(node, gh, timeout_sec=15.0)
if gh.result() is None or not gh.result().accepted:
    fail(node, "Trajectory-Goal abgelehnt (Arm in trajectory-Modus? Schutzstop?)")

rf = gh.result().get_result_async()
rclpy.spin_until_future_complete(node, rf, timeout_sec=goal_to + 15.0)
res = rf.result()
if res is None:
    fail(node, f"kein Ergebnis innerhalb {goal_to}s")
ec = res.result.error_code
if ec == FollowJointTrajectory.Result.SUCCESSFUL:
    print(f"[guten-morgen] Arm in {pose_name} (error_code={ec})", flush=True)
    ok = 0
else:
    print(f"FEHLER: Trajectory nicht erfolgreich (error_code={ec})", file=sys.stderr)
    ok = 1
node.destroy_node(); rclpy.shutdown(); sys.exit(ok)
PY
MOVE_RC=$?
if [ "$MOVE_RC" -ne 0 ]; then
  die "Fahrt nach '${POSE_NAME}' fehlgeschlagen (rc=${MOVE_RC}) - Arm bleibt stehen, bestromt."
fi

log "Guten Morgen: Arm steht in '${POSE_NAME}', bestromt und im Trajectory-Modus (MoveIt-bereit)."
