"""Mock und Roboter fahren DENSELBEN Treiber -- das ist der ganze Punkt.

Der Greifer hat 2026-08-19 vorgefuehrt, was passiert, wenn Mock und Real auseinanderlaufen: der Container lieferte dem
Twin gar kein Fingergelenk, und zwar still, weil es fuer den Greifer keinen E2E-Test gab.  Hier wird die
Nicht-Abweichung deshalb zur Testbedingung: alles ausser der Paketquelle muss in beiden Faellen Byte fuer Byte gleich
sein.

Braucht weder ROS noch Docker.
"""

import copy

import pytest
import yaml

from husky_navigation import rslidar_config as rc


@pytest.fixture
def template() -> dict:
    return yaml.safe_load(rc.TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_online_selects_the_device(template):
    out = rc.render(template)
    assert out["common"]["msg_source"] == rc.MSG_SOURCE_ONLINE


def test_pcap_selects_the_file(template):
    out = rc.render(template, pcap_path="/data/rs16_labor.pcap")
    assert out["common"]["msg_source"] == rc.MSG_SOURCE_PCAP
    assert out["lidar"][0]["driver"]["pcap_path"] == "/data/rs16_labor.pcap"


def test_online_carries_no_pcap_path(template):
    out = rc.render(template)
    assert "pcap_path" not in out["lidar"][0]["driver"], (
        "Ein pcap_path in der Online-Konfiguration ist eine Falle: er sieht "
        "harmlos aus und entscheidet nichts, bis jemand msg_source aendert."
    )


def test_only_the_packet_source_differs(template):
    """Der Kern: alles ausser der Quelle ist in Mock und Live identisch."""
    online = rc.render(copy.deepcopy(template))
    pcap = rc.render(copy.deepcopy(template), pcap_path="/data/x.pcap")

    online["common"].pop("msg_source")
    pcap["common"].pop("msg_source")
    pcap["lidar"][0]["driver"].pop("pcap_path")
    pcap["lidar"][0]["driver"].pop("pcap_repeat")
    pcap["lidar"][0]["driver"].pop("pcap_rate")

    assert online == pcap


def test_the_device_stays_an_rs16_on_both_paths(template):
    for out in (rc.render(copy.deepcopy(template)), rc.render(copy.deepcopy(template), pcap_path="/data/x.pcap")):
        assert out["lidar"][0]["driver"]["lidar_type"] == "RS16"


def test_the_frame_stays_canonical_on_both_paths(template):
    """lidar3d_0_laser ist der Name, den robot.yaml erzeugt -- weicht der
    Treiber davon ab, findet tf2 die Punktwolke nicht und niemand sagt es."""
    for out in (rc.render(copy.deepcopy(template)), rc.render(copy.deepcopy(template), pcap_path="/data/x.pcap")):
        assert out["lidar"][0]["ros"]["ros_frame_id"] == "lidar3d_0_laser"


def test_a_template_without_lidar_section_is_refused():
    with pytest.raises(ValueError, match="lidar"):
        rc.render({"common": {}})


def test_a_template_without_common_section_is_refused():
    with pytest.raises(ValueError, match="common"):
        rc.render({"lidar": [{}]})


def test_write_resolved_produces_loadable_yaml(tmp_path):
    out = rc.write_resolved(tmp_path / "resolved.yaml", pcap_path="/data/rs16_labor.pcap")
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert loaded["common"]["msg_source"] == rc.MSG_SOURCE_PCAP
