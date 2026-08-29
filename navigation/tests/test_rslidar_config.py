"""Mock and robot drive the SAME driver -- that is the whole point.

On 2026-08-19 the gripper demonstrated what happens when mock and real diverge: the container delivered no finger
joint at all to the twin, and it did so silently, because there was no E2E test for the gripper.  Here the
non-divergence therefore becomes the test condition: everything except the packet source has to be byte for byte the
same in both cases.

Needs neither ROS nor Docker.
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
        "A pcap_path in the online configuration is a trap: it looks harmless "
        "and decides nothing, until somebody changes msg_source."
    )


def test_only_the_packet_source_differs(template):
    """The core: everything except the source is identical in mock and live."""
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
    """lidar3d_0_laser is the name robot.yaml generates -- if the driver
    deviates from it, tf2 does not find the point cloud and nobody says so."""
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
