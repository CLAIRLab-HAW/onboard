"""This suite has to come along in the ROOT run, not only in the package run.

``norecursedirs`` in the root pyproject.toml excluded ``robot`` as long as no tests lived there.  A test that ran only
in the package run would fall silent exactly when someone needs it -- the same lesson ``deploy`` has cost once already.

The marker ``nav_e2e`` has to be registered AND deselected by default: it needs a running container with a driving
base, and that is not a precondition a ``uv run pytest`` at the root may silently assume.

This test needs neither ROS nor Docker -- it reads text.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_root_run_descends_into_robot():
    norecurse = _config()["tool"]["pytest"]["ini_options"]["norecursedirs"]
    assert "robot" not in norecurse, (
        "norecursedirs excludes 'robot' -- robot/husky-navigation/tests is "
        "then NOT collected in the root run, and silently at that."
    )


def test_the_nav_e2e_marker_is_registered():
    markers = _config()["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("nav_e2e:") for m in markers), (
        "Marker 'nav_e2e' is not registered -- pytest then warns about an unknown marker on every run."
    )


def test_the_default_run_deselects_nav_e2e():
    addopts = _config()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "not nav_e2e" in addopts, (
        "The root run does not deselect nav_e2e -- it would presuppose a running container with a driving base."
    )


def test_this_package_is_a_workspace_member():
    members = _config()["tool"]["uv"]["workspace"]["members"]
    assert "robot/husky-navigation" in members, (
        "Without a member entry `uv sync` does not resolve the package and "
        "`import husky_navigation` fails in every test."
    )
