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
        capture_output=True, text=True, timeout=timeout)
    return proc.stdout


@pytest.fixture(scope="module")
def container():
    probe = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format",
         "{{range .Config.Env}}{{println .}}{{end}}"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"Container {CONTAINER} laeuft nicht.")
    if "TARGET=mock" not in probe.stdout:
        pytest.skip("Container steht NICHT auf TARGET=mock -- dieser Test "
                    "faehrt den Roboter.")
    return CONTAINER


def test_the_navigate_to_pose_action_is_offered(container):
    """Mit Wiederholung: die Discovery des ros2-Daemons ist asynchron.

    Ein einzelnes `ros2 action list` direkt nach dem Start liefert eine leere
    Liste -- nicht weil die Action fehlt, sondern weil der Daemon seinen
    Graphen noch nicht hat.  Ein Test, der daran scheitert, misst die
    Anlaufzeit des Daemons und nicht Nav2.
    """
    out = _exec("source ros-env; "
                "for i in $(seq 1 10); do "
                "  L=$(timeout 20 ros2 action list 2>/dev/null); "
                "  case \"$L\" in *navigate_to_pose*) echo \"$L\"; exit 0;; esac; "
                "  sleep 3; "
                "done; echo \"$L\"", timeout=260)
    assert "/a200_0553/navigate_to_pose" in out, (
        "bt_navigator bietet die Action nicht an -- ist der "
        f"lifecycle_manager durchgekommen? /tmp/nav.log lesen. Gesehen:\n{out}")


def test_the_map_is_published(container):
    out = _exec("source ros-env; timeout 10 ros2 topic echo /a200_0553/map "
                "--once --field info.resolution 2>/dev/null")
    assert out.strip(), "map_server publiziert keine Karte."


def test_the_map_to_base_link_transform_exists(container):
    """Mit den namespaced TF-Remaps -- ohne sie meldet tf2_echo 'frame does
    not exist' und man sucht eine Transformation, die laengst da ist."""
    out = _exec("source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
                "map base_link --ros-args "
                "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
                "2>&1 | head -20")
    assert "Translation" in out, (
        "Keine TF-Kette map -> base_link. In diesem Stand liefert map -> odom "
        f"der static_transform_publisher und odom -> base_link der EKF. "
        f"Ausgabe:\n{out}")


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
        f"/tmp/nav_goal.log im Container lesen.")
