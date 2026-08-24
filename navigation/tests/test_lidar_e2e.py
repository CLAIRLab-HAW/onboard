"""Der Sensorpfad: echter Treiber, echte Pakete, abgeleiteter Scan.

Ueberspringt sich mit benannter Ursache, solange die RS16-Aufnahme fehlt
(R-Punkt c).  Ein Test, der ohne Aufnahme gruen wuerde, waere schlimmer als
keiner: er meldete eine Kette als gefahren, die nie Pakete gesehen hat.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nav_e2e

CONTAINER = "husky-offboard-offboard-1"
#: Der Mount aus docker-compose.yml (../../data/recordings -> /data/recordings).
PCAP_HOST = Path(__file__).resolve().parents[3] / "data" / "recordings" / "rs16_labor.pcap"
PCAP_CONTAINER = "/data/recordings/rs16_labor.pcap"


def _exec(script: str, timeout: int = 120) -> str:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", script], capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout


@pytest.fixture(scope="module")
def replay():
    if subprocess.run(["docker", "inspect", CONTAINER], capture_output=True).returncode != 0:
        pytest.skip(f"Container {CONTAINER} laeuft nicht.")
    if not PCAP_HOST.is_file():
        pytest.skip(
            f"Keine RS16-Aufnahme unter {PCAP_HOST} -- R-Punkt c in "
            f"ROBOTER-TODO.md (tcpdump auf UDP 6699 + 7788 am Roboter). "
            f"Ohne sie hat der Mock keine Lidardaten."
        )
    _exec("pkill -f rslidar_sdk_node || true; sleep 2")
    _exec(
        f"source ros-env; nohup ros2 launch "
        f"/opt/spact/husky-navigation/launch/lidar.launch.py "
        f"pcap:={PCAP_CONTAINER} > /tmp/lidar.log 2>&1 & sleep 15; echo ok"
    )
    return PCAP_CONTAINER


def test_the_driver_reads_from_the_recording(replay):
    """Verifiziert die msg_source-Zuordnung AM LAUFENDEN KNOTEN.

    Die Werte 1/2/3 stehen in der Doku von RoboSense; hier steht, was der
    Treiber tatsaechlich tut.
    """
    log = _exec("cat /tmp/lidar.log")
    assert "Receive Packets From : Pcap" in log, f"Der Treiber liest nicht aus der Aufnahme. Log:\n{log[-2000:]}"


def test_the_point_cloud_arrives(replay):
    out = _exec("source ros-env; timeout 15 ros2 topic hz " "/a200_0553/sensors/lidar3d_0/points 2>&1 | head -5")
    assert "average rate" in out, f"Keine Punktwolke. Ausgabe:\n{out}"


def test_the_cloud_carries_the_canonical_frame(replay):
    out = _exec(
        "source ros-env; timeout 10 ros2 topic echo "
        "/a200_0553/sensors/lidar3d_0/points --once --field header.frame_id"
    )
    assert "lidar3d_0_laser" in out


def test_the_derived_scan_is_not_all_infinite(replay):
    """Ein Scan aus lauter inf sieht wie ein kaputter Treiber aus und ist in
    Wahrheit ein Hoehenband, das die Fahrebene verfehlt."""
    script = r"""
source ros-env
timeout 15 ros2 topic echo /a200_0553/sensors/lidar3d_0/scan --once --field ranges \
  > /tmp/scan_ranges.txt 2>&1
python3 -c "
import re
text = open('/tmp/scan_ranges.txt').read()
vals = [float(v) for v in re.findall(r'-?\d+\.\d+', text)]
finite = [v for v in vals if v == v and v != float('inf')]
print(len(finite), len(vals))
"
"""
    finite, total = (int(x) for x in _exec(script).strip().splitlines()[-1].split())
    assert total > 0, "Kein LaserScan empfangen."
    assert finite > total * 0.05, (
        f"Nur {finite} von {total} Strahlen sind endlich. Entweder trifft das "
        f"Hoehenband (min_height/max_height in wiring.py) die Fahrebene nicht, "
        f"oder die Aufnahme zeigt freies Feld."
    )


def test_amcl_publishes_the_map_to_odom_transform(replay):
    """Erst mit Scans wird AMCL zur Quelle von map -> odom."""
    _exec("pkill -f 'nav2|lifecycle_manager' || true; sleep 3")
    _exec("nohup nav localization:=amcl > /tmp/nav-amcl.log 2>&1 & sleep 35; echo ok", timeout=120)
    out = _exec(
        "source ros-env; timeout 10 ros2 run tf2_ros tf2_echo map odom "
        "--ros-args -r /tf:=/a200_0553/tf "
        "-r /tf_static:=/a200_0553/tf_static 2>&1 | head -20"
    )
    assert "Translation" in out, f"AMCL publiziert map -> odom nicht. Log:\n" f"{_exec('tail -40 /tmp/nav-amcl.log')}"
