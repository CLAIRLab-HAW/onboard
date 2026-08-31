"""The one call path by which the boot service reaches its three root-owned patch tools.

Three steps of ``clearpath_custom_setup`` are a call to a copy under ``/usr/local/bin`` -- the sensor mesh URIs, the
SRDF gripper group, the URDF physical properties.  What they must have in common is not the tool but the FAILURE
behaviour: a missing or failing patcher degrades that one patch, it never takes the boot down.  The robot is not
here to check that, so the tool path is pointed at a script written on the spot.
"""

from __future__ import annotations

import os
import stat

import clearpath_custom_setup as ccs


def _tool(tmp_path, body, name="fake-patch"):
    path = tmp_path / name
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_it_reports_success_and_relays_the_output(tmp_path, capsys):
    tool = _tool(tmp_path, "print('two files patched')\n")
    assert ccs.run_root_tool("mesh", tool, missing="unused.") is True
    assert "mesh: two files patched" in capsys.readouterr().out


def test_it_relays_stderr_too(tmp_path, capsys):
    """A patcher's warnings are the half that says which measurement or file is missing -- dropping them would
    leave a green log over a patch that did not land."""
    tool = _tool(tmp_path, "import sys; print('no such joint', file=sys.stderr)\n")
    ccs.run_root_tool("physics", tool, missing="unused.")
    assert "physics: no such joint" in capsys.readouterr().out


def test_a_nonzero_exit_is_a_failure_not_an_exception(tmp_path, capsys):
    tool = _tool(tmp_path, "import sys; sys.exit(1)\n")
    assert ccs.run_root_tool("rg6", tool, missing="unused.") is False
    assert "exit code 1" in capsys.readouterr().err


def test_a_missing_tool_names_what_is_lost(tmp_path, capsys):
    """The warning has to say which capability is gone, not only which file -- the log is read by whoever finds
    the gripper missing in MoveIt, not by whoever knows the installer's file list."""
    missing = "MoveIt without the gripper."
    assert ccs.run_root_tool("rg6", str(tmp_path / "never-installed"), missing=missing) is False
    err = capsys.readouterr().err
    assert missing in err and "never-installed" in err


def test_it_passes_the_extra_arguments_through(tmp_path, capsys):
    """``rg6-moveit-patch`` is the one of the three that takes an argument (``--setup-path``); dropping it would
    send the patcher at the wrong tree and it would report success on nothing."""
    tool = _tool(tmp_path, "import sys; print(' '.join(sys.argv[1:]))\n")
    ccs.run_root_tool("rg6", tool, args=("--setup-path", "/etc/clearpath"), missing="unused.")
    assert "--setup-path /etc/clearpath" in capsys.readouterr().out


def test_an_unrunnable_tool_is_caught(tmp_path, capsys):
    """Present but not executable: the installer places these with ``install -m 0755``, so this means somebody
    edited the copy by hand.  An OSError out of here would abort the whole boot service."""
    path = tmp_path / "not-executable"
    path.write_text("#!/usr/bin/env python3\n")
    path.chmod(path.stat().st_mode & ~stat.S_IEXEC & ~stat.S_IXGRP & ~stat.S_IXOTH)
    assert os.path.isfile(path)
    assert ccs.run_root_tool("mesh", str(path), missing="unused.") is False
    assert "call failed" in capsys.readouterr().err
