"""The patcher that puts this vehicle's LOADED wheel radius into the a200 description.

The fixtures are shaped after the line ``clearpath_platform_description`` actually ships, read on the a200-0553 on
2026-09-01 and quoted in the tool's docstring::

    <origin xyz="0 0 ${wheel_vertical_offset - front_wheel_radius}" rpy="0 0 0" />

What is worth testing is not that a string replace replaces a string.  It is the four properties this tool has to
hold, because ``base_footprint`` is the ground reference every calibrated height in the workspace is measured
against: that the ROLLING radius next door (``${front_wheel_radius * 2}``, the odometry wheel diameter) is left
alone, that the second run is a no-op, that the ``.bak`` keeps the PRISTINE apt copy, and -- the one that matters
most -- that a file carrying NEITHER form fails loudly instead of silently leaving the nominal ground reference in
place.
"""

from __future__ import annotations

import ride_height_patch as patch

#: The a200 xacro reduced to the two places that mention the wheel radius.  The ros2_control line is not decoration:
#: it is the near miss this tool must not touch.
STOCK = """<?xml version="1.0"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro">
  <xacro:macro name="a200" params="control:='diff_4wd'">
    <xacro:property name="wheel_vertical_offset" value="0.03282" />
    <ros2_control name="a200_hardware" type="system">
      <hardware>
        <param name="wheel_diameter">${front_wheel_radius * 2}</param>
      </hardware>
    </ros2_control>
    <link name="base_footprint"/>
    <joint name="base_footprint_joint" type="fixed">
      <origin xyz="0 0 ${wheel_vertical_offset - front_wheel_radius}" rpy="0 0 0" />
      <parent link="base_link" />
      <child link="base_footprint" />
    </joint>
  </xacro:macro>
</robot>
"""


def _share(tmp_path, content=STOCK):
    """Lay out a fake ``/opt/ros/<distro>/share`` and return the glob that addresses it."""
    urdf = tmp_path / "jazzy" / "share" / "clearpath_platform_description" / "urdf" / "a200"
    urdf.mkdir(parents=True)
    target = urdf / "a200.urdf.xacro"
    target.write_text(content)
    return str(tmp_path / "*" / "share"), target


def test_the_ground_reference_moves_onto_the_loaded_radius(tmp_path):
    share, target = _share(tmp_path)
    assert patch.main([f"--ros-share={share}"]) == 0
    assert f"front_wheel_radius - {patch.SQUISH_M}" in target.read_text()


def test_the_odometry_wheel_diameter_is_left_alone(tmp_path):
    """``${front_wheel_radius * 2}`` is the ROLLING radius for odometry -- a different quantity, patched elsewhere
    if ever, and deflection does not change it the same way."""
    share, target = _share(tmp_path)
    patch.main([f"--ros-share={share}"])
    assert '<param name="wheel_diameter">${front_wheel_radius * 2}</param>' in target.read_text()


def test_a_second_run_changes_nothing(tmp_path):
    share, target = _share(tmp_path)
    patch.main([f"--ros-share={share}"])
    once = target.read_text()
    assert patch.main([f"--ros-share={share}"]) == 0
    assert target.read_text() == once


def test_the_backup_keeps_the_pristine_apt_copy(tmp_path):
    """A second run must not overwrite the backup with an already-patched file: the diff against the pristine copy
    is the only way to see what a boot changed."""
    share, target = _share(tmp_path)
    patch.main([f"--ros-share={share}"])
    patch.main([f"--ros-share={share}"])
    assert target.with_suffix(".xacro.bak").read_text() == STOCK


def test_an_unrecognised_origin_fails_loudly(tmp_path):
    """Silence here would drop the ground reference back to the nominal radius without anybody noticing -- every
    calibrated height in the workspace would then be 31 mm out, and nothing would say so."""
    share, _ = _share(tmp_path, content=STOCK.replace("wheel_vertical_offset - front_wheel_radius", "0.0"))
    assert patch.main([f"--ros-share={share}"]) == 1


def test_a_missing_package_fails_loudly(tmp_path):
    assert patch.main([f"--ros-share={tmp_path}/*/share"]) == 1


def test_the_dry_run_writes_nothing(tmp_path):
    share, target = _share(tmp_path)
    assert patch.main([f"--ros-share={share}", "--dry-run"]) == 0
    assert target.read_text() == STOCK
