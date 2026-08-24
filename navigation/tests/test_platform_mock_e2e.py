"""Die Basis muss sich im Mock wirklich bewegen -- nicht nur Raeder drehen.

Der teure Irrtum ist hier NICHT "es faehrt nicht", sondern "die Raeder drehen
sich in RViz und die Odometrie meldet Stillstand".  Das sieht nach einem
Nav2-Fehler aus und ist ein URDF-Fehler (fehlendes calculate_dynamics).
Deshalb prueft dieser Test die ODOMETRIE, nicht die Radgelenke.

Braucht einen laufenden Container mit `mock platform:=true`.
"""

import json
import subprocess

import pytest

pytestmark = pytest.mark.nav_e2e

CONTAINER = "husky-offboard-offboard-1"


def _exec(script: str, timeout: int = 90) -> str:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", script], capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout


@pytest.fixture(scope="module")
def container():
    probe = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"Container {CONTAINER} laeuft nicht.")
    if "TARGET=mock" not in probe.stdout:
        pytest.skip(
            "Container steht NICHT auf TARGET=mock -- dieser Test "
            "kommandiert cmd_vel und wuerde den echten Husky fahren."
        )
    return CONTAINER


def test_the_platform_controller_is_active(container):
    out = _exec("source ros-env; ros2 control list_controllers " "-c /a200_0553/controller_manager 2>/dev/null")
    assert "platform_velocity_controller" in out, (
        "Der Radcontroller ist nicht geladen -- `mock platform:=true` " "gestartet?"
    )
    assert "active" in out


def test_only_the_platform_hardware_is_claimed_by_the_platform_manager(container):
    """Das Risiko aus Spec Paragraph 3.4: ein controller_manager laedt ALLE
    ros2_control-Bloecke des URDF, das er bekommt."""
    out = _exec("source ros-env; ros2 control list_hardware_components " "-c /a200_0553/controller_manager 2>/dev/null")
    assert "a200_hardware" in out
    assert "arm_0" not in out, (
        "Der Plattform-Manager beansprucht auch die Arm-Hardware -- dann "
        "streiten sich zwei controller_manager um dieselben Gelenke. "
        "Ausweichweg: eigenes, mit use_manipulation_controllers:=false "
        "prozessiertes URDF als Parameter (Spec Paragraph 3.4)."
    )


def test_driving_forward_moves_the_odometry(container, exclusive_base):
    """Der Kern: cmd_vel rein, Wegstrecke raus."""
    script = r"""
source ros-env
# head -1: `--once` haengt eine "---"-Zeile an, an der float() scheitert.
#
# Mit Wiederholung: unter Last (Mock + Nav2 = gut drei Dutzend Knoten) kommt
# das echo gelegentlich leer zurueck, und float("") beendet die Messung mit
# einem Fehler, der nach "keine Odometrie" aussieht und keiner ist.  Fuenf
# Versuche, dann ist es wirklich still.
read_x() {
  for _ in 1 2 3 4 5; do
    V=$(timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
          --field pose.pose.position.x 2>/dev/null | head -1)
    case "$V" in ''|*[!0-9.eE+-]*) sleep 2;; *) echo "$V"; return 0;; esac
  done
  echo ""
}
BEFORE=$(read_x)
# Richtung IMMER zur Kartenmitte hin.  Faehrt der Test stets vorwaerts,
# wandert der Roboter ueber viele Laeufe aus der 10-m-Karte heraus -- am
# 2026-08-22 gemessen: bei x=4,63 lehnte Nav2 das naechste Ziel ab und der
# Nachbartest mass 0,000 m.  So bleibt er beliebig oft wiederholbar.
VX=$(python3 -c "import sys; print(-0.2 if float(sys.argv[1]) > 0 else 0.2)" "$BEFORE")
# Fahrfenster 8 s, Messschwelle 0,3 m -- bewusst weit auseinander.
#
# `ros2 topic pub` braucht unter Last ein bis zwei Sekunden, bis das erste
# Kommando auf dem Draht ist (Knoten anlegen, Discovery).  Mit `timeout 3`
# blieben davon knapp 1 s Fahrt uebrig, und der Test mass 0,155-0,18 m statt
# 0,6 m -- er mass also die Anlaufzeit des CLI, nicht die Basis.  Am
# 2026-08-22 dreimal reproduziert.
#
# 8 s ergeben selbst mit 2 s Anlauf rund 1,2 m.  Die Schwelle bleibt bei
# 0,3 m: weit ueber der Encoder-Drift (~0,01 rad) und weit unter dem
# Erwartungswert, also unempfindlich gegen Last und trotzdem aussagekraeftig.
timeout 8 ros2 topic pub -r 20 /a200_0553/cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: base_link}, twist: {linear: {x: $VX}}}" > /dev/null 2>&1
sleep 1
AFTER=$(read_x)
python3 -c "import json;print(json.dumps({'before': float('''$BEFORE'''), 'after': float('''$AFTER''')}))"
"""
    result = json.loads(_exec(script).strip().splitlines()[-1])
    travelled = abs(result["after"] - result["before"])
    assert travelled > 0.3, (
        f"0,2 m/s ueber 8 s sollten rund 1,2 m ergeben (Schwelle 0,3 m), "
        f"gemessen wurden "
        f"{travelled:.3f} m (vorher {result['before']:.3f}, nachher "
        f"{result['after']:.3f}). Bleibt der Wert bei 0, fehlt "
        f"calculate_dynamics an der Mock-Hardware."
    )


def test_the_odom_to_base_link_transform_exists(container):
    """Die TF-Remaps sind hier kein Detail, sondern der ganze Test.

    tf2 broadcastet auf die ABSOLUTEN Namen /tf und /tf_static; der Graph
    dieses Roboters haelt sie aber unter /a200_0553/tf.  Ein tf2_echo ohne
    diese Remaps meldet 'Invalid frame ID "odom" ... frame does not exist' --
    das sieht aus wie eine fehlende Transformation und ist ein Hoerfehler.
    """
    out = _exec(
        "source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
        "odom base_link --ros-args "
        "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
        "2>&1 | head -20"
    )
    assert "Translation" in out, (
        "Keine TF-Kante odom -> base_link. Sie kommt vom ekf_node, NICHT vom "
        "Radcontroller (enable_odom_tf: False in control.yaml) -- laeuft der "
        f"EKF? Ausgabe:\n{out}"
    )
