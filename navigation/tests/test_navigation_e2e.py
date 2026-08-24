"""Nav2 faehrt im Mock -- gegen eine Karte, OHNE Lokalisierung.

Der Testname sagt es ausdruecklich: in diesem Stand traegt allein die
Radodometrie, der Roboter driftet gegen die Karte, und die Costmap hat keine
Hindernisse.  Wer diesen Test spaeter fuer einen Lokalisierungsnachweis
haelt, liest ihn falsch -- den liefert erst der Sensorpfad.

Braucht einen laufenden Container mit `mock platform:=true` und `nav`.
"""

import json
import subprocess

import pytest

pytestmark = pytest.mark.nav_e2e

CONTAINER = "husky-offboard-offboard-1"


def _exec(script: str, timeout: int = 180) -> str:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout


@pytest.fixture(scope="module")
def container():
    probe = subprocess.run(
        [
            "docker",
            "inspect",
            CONTAINER,
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"Container {CONTAINER} laeuft nicht.")
    if "TARGET=mock" not in probe.stdout:
        pytest.skip(
            "Container steht NICHT auf TARGET=mock -- dieser Test "
            "faehrt den Roboter."
        )
    return CONTAINER


def test_the_navigate_to_pose_action_is_offered(container):
    """Mit Wiederholung: die Discovery des ros2-Daemons ist asynchron.

    Ein einzelnes `ros2 action list` direkt nach dem Start liefert eine leere
    Liste -- nicht weil die Action fehlt, sondern weil der Daemon seinen
    Graphen noch nicht hat.  Ein Test, der daran scheitert, misst die
    Anlaufzeit des Daemons und nicht Nav2.
    """
    out = _exec(
        "source ros-env; "
        "for i in $(seq 1 10); do "
        "  L=$(timeout 20 ros2 action list 2>/dev/null); "
        '  case "$L" in *navigate_to_pose*) echo "$L"; exit 0;; esac; '
        "  sleep 3; "
        'done; echo "$L"',
        timeout=260,
    )
    assert "/a200_0553/navigate_to_pose" in out, (
        "bt_navigator bietet die Action nicht an -- ist der "
        f"lifecycle_manager durchgekommen? /tmp/nav.log lesen. Gesehen:\n{out}"
    )


def test_the_map_is_published(container):
    out = _exec(
        "source ros-env; timeout 10 ros2 topic echo /a200_0553/map "
        "--once --field info.resolution 2>/dev/null"
    )
    assert out.strip(), "map_server publiziert keine Karte."


def test_the_map_to_base_link_transform_exists(container):
    """Mit den namespaced TF-Remaps -- ohne sie meldet tf2_echo 'frame does
    not exist' und man sucht eine Transformation, die laengst da ist."""
    out = _exec(
        "source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
        "map base_link --ros-args "
        "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
        "2>&1 | head -20"
    )
    assert "Translation" in out, (
        "Keine TF-Kette map -> base_link. In diesem Stand liefert map -> odom "
        f"der static_transform_publisher und odom -> base_link der EKF. "
        f"Ausgabe:\n{out}"
    )


def test_navigates_without_localization(container, exclusive_base):
    """Ein Ziel 1 m entfernt -- und die Odometrie sagt, ob er dort ankam.

    Bewusst NICHT: 'RViz sieht gut aus'.  Ein laufender Prozess ist kein
    Beleg, und eine Pose kann aus jedem Blickwinkel plausibel wirken.
    """
    script = r"""
source ros-env
# Mit Wiederholung -- s. test_platform_mock_e2e.py: unter Last kommt das
# echo gelegentlich leer zurueck.
read_x() {
  for _ in 1 2 3 4 5; do
    V=$(timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
          --field pose.pose.position.x 2>/dev/null | head -1)
    case "$V" in ''|*[!0-9.eE+-]*) sleep 2;; *) echo "$V"; return 0;; esac
  done
  echo ""
}
BEFORE=$(read_x)
# Die Karte ist 10 x 10 m mit Ursprung in der Mitte -- x reicht von -5 bis
# +5.  Ein Ziel "immer 1 m weiter vorne" fuehrt den Roboter nach genug
# Testlaeufen aus der Karte heraus, und Nav2 lehnt es dann ab (am 2026-08-22
# gemessen: bei x=4,63 wurden 0,000 m gefahren).  Deshalb immer ZUR MITTE hin.
GOAL=$(python3 -c "import sys; x=float(sys.argv[1]); print(x - 1.0 if x > 0 else x + 1.0)" "$BEFORE")
timeout 120 ros2 action send_goal /a200_0553/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: $GOAL, y: 0.0, z: 0.0},
    orientation: {w: 1.0}}}}" > /tmp/nav_goal.log 2>&1
AFTER=$(read_x)
python3 -c "import json;print(json.dumps({'before': float('''$BEFORE'''), 'after': float('''$AFTER''')}))"
"""
    result = json.loads(_exec(script, timeout=200).strip().splitlines()[-1])
    travelled = abs(result["after"] - result["before"])
    assert travelled > 0.7, (
        f"Ziel war 1,0 m entfernt (zur Kartenmitte hin), gefahren wurden "
        f"{travelled:.3f} m "
        f"(vorher {result['before']:.3f}, nachher {result['after']:.3f}). "
        f"/tmp/nav_goal.log im Container lesen."
    )


def test_navigates_to_a_goal_it_has_to_turn_around_for(container, exclusive_base):
    """Ein Ziel, das eine grosse Richtungsaenderung verlangt.

    Der Nachbartest faehrt bewusst immer ZUR Kartenmitte hin -- also
    praktisch geradeaus.  Genau deshalb hat er am 2026-08-22 nicht gemerkt,
    dass der Husky bei einer Wende haengenblieb: in derselben Runde lief ein
    Ziel geradeaus in 12 s durch, waehrend das Ziel (-2|2) aus (1,93|1,78)
    nach 51 s ganze 0,06 m gefahren war und dann ABORTED meldete.

    Dieser Test dreht den Roboter vorher ABSICHTLICH vom Ziel weg und prueft,
    ob er trotzdem ankommt.  Er faellt aus, wenn der RotationShimController
    fehlt oder der Antrieb die Drehung nicht ausfuehrt.
    """
    script = r"""
source ros-env
read_odom() {   # -> "x y yaw"
  for _ in 1 2 3 4 5; do
    timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
      --field pose.pose 2>/dev/null | grep -E '^  [xyzw]: ' > /tmp/o.txt
    # pose.pose druckt position(x,y,z) dann orientation(x,y,z,w) -> 7 Werte-
    # zeilen, jeweils mit ZWEI fuehrenden Leerzeichen (am 2026-08-22 mit
    # `cat -A` nachgesehen; mit vier gerechnet und der grep lief leer).
    if [ "$(wc -l < /tmp/o.txt)" = "7" ]; then
      python3 -c "
import math
v=[float(l.split(': ')[1]) for l in open('/tmp/o.txt')]
px,py,_,qx,qy,qz,qw = v
print('%.4f %.4f %.4f' % (px, py,
      math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))))"
      return 0
    fi
    sleep 2
  done
  echo ""
}
read -r X0 Y0 YAW0 <<< "$(read_odom)"

# Zielrichtung IMMER zur Kartenmitte -- sonst wandert der Roboter ueber viele
# Laeufe aus der 10-m-Karte heraus und Nav2 lehnt das Ziel ab.  Steht er
# schon fast in der Mitte, ist die Richtung beliebig; dann +x.
read -r GX GY THETA <<< "$(python3 -c "
import math,sys
x,y = float('$X0'), float('$Y0')
r = math.hypot(x,y)
th = math.atan2(-y,-x) if r > 0.3 else 0.0
print('%.4f %.4f %.4f' % (x+1.2*math.cos(th), y+1.2*math.sin(th), th))")"

# Erst WEGDREHEN: Ziel-Blickrichtung ist theta+pi, also genau vom Ziel fort.
# spin dreht RELATIV, deshalb die Differenz zum aktuellen Yaw ausrechnen und
# auf [-pi,pi] normieren.
DELTA=$(python3 -c "
import math
d = ($THETA + math.pi) - $YAW0
while d >  math.pi: d -= 2*math.pi
while d < -math.pi: d += 2*math.pi
print('%.4f' % d)")
timeout 60 ros2 action send_goal /a200_0553/spin nav2_msgs/action/Spin \
  "{target_yaw: $DELTA}" > /dev/null 2>&1

read -r X1 Y1 YAW1 <<< "$(read_odom)"
S=$SECONDS
STATUS=$(timeout 120 ros2 action send_goal /a200_0553/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: $GX, y: $GY, z: 0.0},
    orientation: {w: 1.0}}}}" 2>&1 | grep -oE 'SUCCEEDED|ABORTED|CANCELED' | tail -1)
DUR=$((SECONDS-S))
read -r X2 Y2 YAW2 <<< "$(read_odom)"
python3 -c "
import json,math
print(json.dumps({
  'status': '$STATUS',
  'seconds': $DUR,
  'goal': [$GX, $GY],
  'yaw_before_goal': $YAW1,
  'travelled': math.hypot($X2-($X1), $Y2-($Y1)),
  'remaining': math.hypot($X2-($GX), $Y2-($GY)),
}))"
"""
    result = json.loads(_exec(script, timeout=320).strip().splitlines()[-1])

    assert result["status"] == "SUCCEEDED", (
        f"Das Ziel hinter dem Roboter endete mit {result['status']!r} nach "
        f"{result['seconds']} s; gefahren wurden {result['travelled']:.3f} m, "
        f"es fehlen {result['remaining']:.3f} m. Ohne den "
        f"RotationShimController bleibt der Husky bei grossen "
        f"Richtungsaenderungen stehen -- pruefe, ob FollowPath.plugin noch "
        f"RotationShimController ist."
    )
    assert result["travelled"] > 0.8, (
        f"Nav2 meldet SUCCEEDED, aber die Odometrie sieht nur "
        f"{result['travelled']:.3f} m -- das Ziel lag 1,2 m entfernt. Ein "
        f"Erfolg ohne Bewegung ist kein Erfolg."
    )
    assert result["remaining"] < 0.35, (
        f"Angekommen ist er nicht: {result['remaining']:.3f} m zum Ziel "
        f"(xy_goal_tolerance ist 0,25)."
    )


def test_the_controller_actually_receives_odometry(container):
    """Ein eingestelltes Topic ist noch keine Datenquelle.

    In ROS 2 taucht ein Topic in `topic list` schon auf, wenn es nur
    ABONNIERT wird.  Am 2026-08-22 stand der controller_server auf dem
    Default "odom", war dort der einzige Teilnehmer -- Publisher count: 0 --
    und bekam nie eine Geschwindigkeit.  Der statische Parametertest haette
    das nicht gefunden, ein falscher Topicname sieht dort aus wie ein
    richtiger.  Deshalb hier: gibt es einen Publisher, und kommen Daten an?
    """
    topic = _exec(
        "source ros-env; timeout 15 ros2 param get "
        "/a200_0553/controller_server odom_topic 2>/dev/null "
        "| tail -1 | sed 's/.*: //'"
    ).strip()
    assert topic, "odom_topic ist am laufenden controller_server nicht lesbar."

    full = topic if topic.startswith("/") else f"/a200_0553/{topic}"
    info = _exec(
        f"source ros-env; timeout 20 ros2 topic info -v {full} "
        "2>/dev/null | grep 'Publisher count'"
    )
    assert "Publisher count: 0" not in info, (
        f"Auf {full} publiziert NIEMAND -- der controller_server bekommt "
        f"seine Ist-Geschwindigkeit nie, `speed` bleibt 0, und der Regler "
        f"regelt blind. Sichtbar wird das als kriechende Drehung (0,05 rad/s "
        f"statt 0,8), nicht als Fehlermeldung. Gesehen: {info.strip()!r}"
    )

    sample = _exec(
        f"source ros-env; timeout 8 ros2 topic echo {full} --once "
        "--field twist.twist.angular.z 2>/dev/null | head -1"
    )
    assert sample.strip(), f"{full} hat einen Publisher, liefert aber keine Daten."


def test_the_ground_frame_matches_the_wheel_geometry(container):
    """base_footprint muss dort liegen, wo die Raeder den Boden beruehren.

    Die Probe verbindet zwei Quellen, die nichts voneinander wissen: das
    URDF (Radachse, base_footprint) und control.yaml (wheel_radius, mit dem
    der DiffDriveController die Odometrie rechnet).  Passen sie nicht
    zusammen, ist entweder die Darstellung falsch oder -- schlimmer -- die
    Odometrie, und Letzteres faellt an nichts auf.  Wer z. B. auf
    Outdoor-Raeder wechselt und nur eine der beiden Stellen nachzieht,
    bekommt hier einen Fehlschlag statt eines stillen Fahrfehlers.

    Am 2026-08-22 gemessen: Radachse +0,03282 ueber base_link, Radradius
    0,1651, base_footprint bei -0,13228 -- exakt die Differenz.

    NICHT geprueft wird, ob base_footprint auf der odom-Ebene liegt: der EKF
    laeuft mit `base_link_frame: base_link` und `two_d_mode: True`, pinnt
    also base_link auf z=0.  Der ganze Roboter steht dadurch 13,2 cm unter
    der Bodenebene der Karte, was in RViz und Foxglove sichtbar ist und wie
    ein Fehler aussieht.  Es ist Clearpaths Konvention aus der generierten
    localization.yaml, ueber robot.yaml nicht einstellbar, und fuer Nav2
    folgenlos -- dort zaehlen nur x, y und yaw.
    """

    def _z(parent: str, child: str) -> float:
        out = _exec(
            f"source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
            f"{parent} {child} --ros-args "
            "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
            "2>&1 | grep -m1 Translation"
        )
        assert "Translation" in out, f"Keine TF {parent} -> {child}: {out!r}"
        return float(out.split("[")[1].split("]")[0].split(",")[2])

    footprint_z = _z("base_link", "base_footprint")
    axle_z = _z("base_link", "front_left_wheel_link")

    radius = float(
        _exec(
            "grep -m1 'wheel_radius:' /clearpath/platform/config/control.yaml "
            "| tr -d ' ' | cut -d: -f2"
        ).strip()
    )

    expected = axle_z - radius
    assert abs(footprint_z - expected) < 0.005, (
        f"base_footprint liegt bei {footprint_z:.5f}, die Raeder beruehren "
        f"den Boden aber bei {expected:.5f} (Achse {axle_z:.5f} minus "
        f"Radradius {radius} aus control.yaml). URDF und Radcontroller "
        f"rechnen mit verschiedenen Raedern -- dann ist auch die Odometrie "
        f"um denselben Faktor falsch, und das meldet niemand."
    )
