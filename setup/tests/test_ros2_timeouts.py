"""Every ``timeout`` around a ros2 CLI call on the robot carries a kill grace (``-k``).

The ros2 CLI (rmw_zenoh 0.2.10, ros2cli 0.32.12) ignores the SIGTERM ``timeout`` sends: a ``timeout 3 ros2 topic
echo`` on a silent topic ran 97.9 s, ``timeout -k 2 3`` ended after 5.0 s (a200-0553, 2026-09-29). Without the
grace the manipulators watchdog hung in its health check and never restarted a UR driver that had died at boot, and
``wakeup.sh`` hung in its ``prepare`` call.
"""

from __future__ import annotations

import re
from pathlib import Path

SETUP = Path(__file__).resolve().parents[1]
#: ``timeout`` followed by its duration and then ``ros2``, on one line: the form every script here uses.
WRAPPED = re.compile(r"\btimeout\s+(?P<args>[^|;&]*?)\bros2\s")


def test_every_timeout_around_ros2_kills_after_a_grace():
    scripts = sorted(SETUP.rglob("*.sh"))
    assert scripts, "no shell scripts found under onboard/setup"
    offenders = []
    for script in scripts:
        for number, line in enumerate(script.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for match in WRAPPED.finditer(line):
                if not match.group("args").lstrip().startswith("-k "):
                    offenders.append(f"{script.relative_to(SETUP)}:{number}: {line.strip()}")
    assert not offenders, "timeout without -k around ros2:\n" + "\n".join(offenders)
