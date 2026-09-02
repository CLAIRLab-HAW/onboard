"""The patcher that turns Clearpath's sensor mesh URIs from ``file://`` into ``package://``.

Unlike ``test_urdf_physics_patch.py`` there is no real upstream file to run against: the workspace bundle under
``urdf/`` carries ``realsense2_description`` (the meshes) but not ``clearpath_sensors_description`` (the four xacros
that point at them), so every fixture here is synthetic.  They are shaped after the line the .deb actually contains,
read on the a200-0553 on 2026-08-20 and quoted in the tool's docstring::

    <mesh filename="file://$(find realsense2_description)/meshes/d435.dae"/>

What is worth testing is not that a string replace replaces a string.  It is the three properties the two former
implementations -- the boot service's ``fix_realsense_mesh_uris`` and the offboard Dockerfile's heredoc -- had to
agree on and could only be checked by reading both: that a foreign ``$(find ...)`` is left alone, that the second run
is a no-op, and that the ``.bak`` keeps the PRISTINE apt copy rather than an already-patched one.
"""

from __future__ import annotations

import sensor_mesh_uri_patch as patch

#: One of the four intel xacros, in the form the package ships.
STOCK = """<?xml version="1.0"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro">
  <xacro:macro name="intel_realsense" params="name parent *origin">
    <link name="${name}_link">
      <visual>
        <geometry>
          <mesh filename="file://$(find realsense2_description)/meshes/d435.dae"/>
        </geometry>
      </visual>
      <collision>
        <geometry><box size="0.02 0.09 0.025"/></geometry>
      </collision>
    </link>
  </xacro:macro>
</robot>
"""


def _share(tmp_path, name="_d435.urdf.xacro", content=STOCK):
    """Lay out a fake ``/opt/ros/<distro>/share`` and return the glob that addresses it."""
    urdf = tmp_path / "jazzy" / "share" / "clearpath_sensors_description" / "urdf" / "intel"
    urdf.mkdir(parents=True)
    (urdf / name).write_text(content)
    return str(tmp_path / "*" / "share"), urdf / name


# ---- the swap itself ------------------------------------------------------------------------------------------


def test_it_rewrites_the_realsense_uri(tmp_path):
    share, xacro = _share(tmp_path)
    assert patch.main(["--ros-share", share]) == 0
    assert 'filename="package://realsense2_description/meshes/d435.dae"' in xacro.read_text()


def test_it_leaves_a_foreign_find_alone(tmp_path):
    """``$(find rg6_description)`` is the gripper's, and its meshes reach Foxglove another way.

    An anchor on ``file://$(find `` alone would take it with it -- which is why the constant carries the package
    name rather than just the scheme.
    """
    foreign = STOCK.replace("realsense2_description)/meshes/d435.dae", "rg6_description)/meshes/hand.dae")
    share, xacro = _share(tmp_path, content=foreign)
    patch.main(["--ros-share", share])
    assert xacro.read_text() == foreign


def test_it_changes_nothing_else_in_the_file(tmp_path):
    """A patcher on a file this workspace does not own touches the one attribute and no other line."""
    import difflib

    share, xacro = _share(tmp_path)
    patch.main(["--ros-share", share])
    changed = [
        line
        for line in difflib.unified_diff(STOCK.splitlines(), xacro.read_text().splitlines(), n=0, lineterm="")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert len(changed) == 2, changed  # exactly one line, removed and added


def test_the_second_run_is_a_no_op(tmp_path):
    share, xacro = _share(tmp_path)
    patch.main(["--ros-share", share])
    once = xacro.read_text()
    patch.main(["--ros-share", share])
    assert xacro.read_text() == once


# ---- what the two former implementations disagreed about ------------------------------------------------------


def test_the_backup_keeps_the_pristine_apt_copy(tmp_path):
    """Taken ONCE, so a second boot cannot overwrite the untouched copy with an already-patched one.

    That is the whole worth of the ``.bak``: the diff against it is the only way to see what a boot changed.
    """
    share, xacro = _share(tmp_path)
    patch.main(["--ros-share", share])
    backup = xacro.with_suffix(xacro.suffix + ".bak")
    assert backup.read_text() == STOCK
    patch.main(["--ros-share", share])
    assert backup.read_text() == STOCK


def test_the_backup_is_not_itself_a_patch_target(tmp_path):
    """``*.urdf.xacro`` must not match ``*.urdf.xacro.bak`` -- otherwise the backup is patched along with the file
    and stops being a record of the state before."""
    share, xacro = _share(tmp_path)
    patch.main(["--ros-share", share])
    assert patch.MESH_URI_OLD in xacro.with_suffix(xacro.suffix + ".bak").read_text()


def test_dry_run_writes_nothing(tmp_path):
    share, xacro = _share(tmp_path)
    assert patch.main(["--ros-share", share, "--dry-run"]) == 0
    assert xacro.read_text() == STOCK
    assert not xacro.with_suffix(xacro.suffix + ".bak").exists()


# ---- the two ways of finding nothing, which are not the same thing --------------------------------------------


def test_an_empty_glob_warns_and_exits_nonzero(tmp_path, capsys):
    """No xacro at all means the package is gone or moved -- loud in BOTH deployments, each at its own severity.

    The nonzero exit is what fails the offboard image build, the one moment the loss can still be caught (apt
    never runs again in the image).  The boot service is not taken down by it: run_root_tool logs the failure
    and carries on, so on the robot a missing sensor package costs the camera model in Foxglove, not the boot.
    """
    assert patch.main(["--ros-share", str(tmp_path / "*" / "share")]) == 1
    assert "WARN" in capsys.readouterr().err


def test_a_failed_rewrite_shows_in_the_exit_code(tmp_path, monkeypatch, capsys):
    """A write failure must not hide behind the steady-state line: exit nonzero, and the summary names the file."""
    share, xacro = _share(tmp_path)

    def refuse(path, content):
        raise OSError("read-only file system")

    monkeypatch.setattr(patch, "atomic_write", refuse)
    assert patch.main(["--ros-share", share]) == 1
    err = capsys.readouterr().err
    assert "_d435.urdf.xacro" in err
    assert patch.MESH_URI_OLD in xacro.read_text()


def test_a_failed_backup_does_not_stop_the_rewrite(tmp_path, monkeypatch, capsys):
    """The fix outranks the undo record: without the .bak the diff is gone, with file:// the camera model is."""
    share, xacro = _share(tmp_path)

    def refuse(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(patch.shutil, "copy2", refuse)
    assert patch.main(["--ros-share", share]) == 0
    assert "no backup" in capsys.readouterr().err
    assert patch.MESH_URI_NEW in xacro.read_text()


def test_already_patched_is_not_a_warning(tmp_path, capsys):
    """The steady state on the robot: the boot service re-runs every boot and finds its own work done."""
    share, _ = _share(tmp_path, content=STOCK.replace(patch.MESH_URI_OLD, patch.MESH_URI_NEW))
    assert patch.main(["--ros-share", share]) == 0
    assert "WARN" not in capsys.readouterr().err


# ---- one implementation, on this side too ---------------------------------------------------------------------


def test_the_boot_service_delegates_instead_of_restating_the_swap():
    """The counterpart to ``test_mesh_uri_single_source.py`` in husky-offboard, which guards the container's half.

    The boot service used to carry the swap as a function of its own, and the offboard Dockerfile a heredoc; this
    tool is what replaced both.  A copy reintroduced HERE would be just as silent as one reintroduced there.
    """
    from pathlib import Path

    boot = Path(__file__).resolve().parents[1] / "scripts" / "clearpath_custom_setup.py"
    code = "\n".join(line for line in boot.read_text().splitlines() if not line.lstrip().startswith("#"))
    restated = sorted(t for t in (patch.MESH_URI_OLD, patch.MESH_URI_NEW) if t in code)
    assert not restated, f"clearpath_custom_setup states the mesh URI swap itself again: {restated}"
    assert "sensor-mesh-uri-patch" in code, "the boot service no longer calls the patcher -- step 2 does nothing."
