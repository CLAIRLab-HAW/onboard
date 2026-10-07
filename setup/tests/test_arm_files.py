"""The files ``robot.yaml``'s arm names by path are in this checkout, where the robot's clone has them.

The UR driver reads the kinematics calibration and the RTDE input recipe straight out of the clone
(``/home/robot/onboard``); nothing copies them anywhere.  The installer's ``arm_files`` reads both paths out of
``robot.yaml`` for its rollout check and for ``--verify``, so this runs that very function: a path it cannot parse,
or one outside the clone, fails here instead of as a robot without a model.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SETUP = Path(__file__).resolve().parents[1]
INSTALLER = SETUP / "install-clearpath-custom-setup.sh"
#: Where the installer clones the repo on the robot (``ONBOARD_WS``), as ``robot.yaml`` spells it.
ROBOT_SETUP = "/home/robot/onboard/setup/"


def arm_files() -> list[str]:
    lines = INSTALLER.read_text().splitlines()
    start = lines.index("arm_files() {")
    function = "\n".join(lines[start : lines.index("}", start) + 1])
    result = subprocess.run(
        ["bash", "-c", f'{function}\narm_files "$1"', "_", str(SETUP / "config/robot.yaml")],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.split()


def test_robot_yaml_names_the_calibration_and_the_recipe_in_the_clone():
    files = arm_files()
    assert [Path(f).name for f in files] == ["ur5_a200_0553_calibration.yaml", "rtde_input_recipe_no_tool.txt"]
    for path in files:
        assert path.startswith(ROBOT_SETUP), f"{path} is outside the clone -- the installer would not roll it out"
        assert (SETUP / path.removeprefix(ROBOT_SETUP)).is_file(), f"{path} names no file in this checkout"
