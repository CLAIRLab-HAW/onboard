"""The one place where mock and robot are allowed to differ.

rslidar_sdk takes ONE yaml file via the ROS parameter ``config_path`` and knows no way to override individual keys.
Whoever wants to drive mock and live from a single source anyway therefore has to render the file instead of
duplicating it -- two maintained yaml files would be exactly the drift source this undertaking sets out to avoid.

ROS-free and therefore testable on the Mac.
"""

from __future__ import annotations

from pathlib import Path

import yaml

#: Values of common.msg_source.  The order of the log lines in the binary is
#: "Online LiDAR", "ROS", "Pcap" -- so 1, 2, 3.  That is verified against the
#: start-up line of the running node, not here.
MSG_SOURCE_ONLINE = 1
MSG_SOURCE_ROS = 2
MSG_SOURCE_PCAP = 3

#: How fast the recording is played back relative to real time.
#: 1 = real time.  Faster would be worthless for Nav2: the costmap reckons in
#: seconds, not in frames.
PCAP_RATE = 1

TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "config" / "rslidar_rs16.yaml"


def render(template: dict, *, pcap_path: str | None = None) -> dict:
    """Sets the packet source in a loaded template.

    ``pcap_path=None`` ─▶ the device.  Otherwise ─▶ the recording.  The template is modified and returned (the caller
    hands over a freshly loaded dict anyway).
    """
    if "common" not in template:
        raise ValueError(
            "Template without a 'common' section -- rslidar_sdk finds msg_source "
            "there and would receive nothing at all without any message."
        )
    if not template.get("lidar"):
        raise ValueError(
            "Template without a 'lidar' section -- without it the driver knows neither device type nor target frame."
        )

    driver = template["lidar"][0].setdefault("driver", {})

    if pcap_path is None:
        template["common"]["msg_source"] = MSG_SOURCE_ONLINE
        for key in ("pcap_path", "pcap_repeat", "pcap_rate"):
            driver.pop(key, None)
    else:
        template["common"]["msg_source"] = MSG_SOURCE_PCAP
        driver["pcap_path"] = pcap_path
        driver["pcap_repeat"] = True
        driver["pcap_rate"] = PCAP_RATE

    return template


def write_resolved(out_path: str | Path, *, pcap_path: str | None = None) -> Path:
    """Renders the template and writes it -- the path goes to ``config_path``."""
    template = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    resolved = render(template, pcap_path=pcap_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    return out
