"""Launch files must not state the wiring a second time.

On the Mac launch_ros is not installed -- a launch file cannot be imported here and its content cannot be checked.
What remains checkable is provenance: if a topic name stands as a string literal IN the launch file, it is stated there
a second time and can drift away from the checked version without any test noticing.

The same lesson as with scripts/guard and scripts/mock -- a comment saying "keep in sync when changing" is not a
mechanism.
"""

from pathlib import Path

import pytest

LAUNCH_DIR = Path(__file__).resolve().parents[1] / "launch"

#: Values that may stand in exactly one place: in clair.navigation.wiring.
WIRED_LITERALS = ("/a200_0553/sensors/lidar3d_0/points", "/a200_0553/sensors/lidar3d_0/scan", "lidar3d_0_laser")


@pytest.mark.parametrize("launch_file", sorted(LAUNCH_DIR.glob("*.launch.py")), ids=lambda p: p.name)
def test_the_launch_file_imports_the_wiring(launch_file):
    text = launch_file.read_text(encoding="utf-8")
    assert "clair.navigation" in text, (
        f"{launch_file.name} does not import clair.navigation -- the wiring then stands there a second time."
    )


@pytest.mark.parametrize("launch_file", sorted(LAUNCH_DIR.glob("*.launch.py")), ids=lambda p: p.name)
def test_the_launch_file_restates_no_wired_literal(launch_file):
    text = launch_file.read_text(encoding="utf-8")
    restated = [lit for lit in WIRED_LITERALS if lit in text]
    assert not restated, (
        f"{launch_file.name} states {restated} itself. These values belong in "
        f"clair.navigation.wiring -- the launch file fetches them instead of "
        f"mirroring them."
    )
