"""The a200-0553's URDF extras: does the file still say what the rest of the workspace assumes it says?

There is nothing to execute here -- the package is data -- so what the tests guard is the seam, and a seam is exactly
what a move breaks:

* an XML comment cannot contain ``--``, and a file that is not well-formed takes the WHOLE stack down with it
  (``mock`` dies in ``_process_urdf``, ``move_group`` never comes up).  That has happened once already, in
  ``onrobot-rg6`` on 2026-08-30, and it stayed invisible until an image rebuild;
* every ``package://`` URI has to name the package that actually ships the file, otherwise RViz and the
  foxglove_bridge draw a robot with holes in it and nothing errors;
* ``robot.yaml`` addresses this file by ABSOLUTE path and lists the workspace it is installed from.  Two numbers
  in a foreign repo, and if either stops matching, the next boot generates a robot without extras.

The last one reaches into ``setup/``.  That is deliberate and follows the workspace convention: a repo
checked out on its own cannot know where its siblings are and skips, but inside a workspace a missing file FAILS rather
than skipping quietly.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "husky_extras_description"
EXTRAS = REPO / "src" / PACKAGE / "urdf" / "clearpath_extras.urdf.xacro"
#: The end effectors ``end_effector:=<name>`` selects, one file each.
TOOLS = sorted((EXTRAS.parent / "tools").glob("*.urdf.xacro"))
#: Every xacro file of every package here -- tools, the macros they call, the other robots' descriptions.
XACROS = sorted((REPO / "src").rglob("*.xacro"))

#: The absolute path robot.yaml addresses this file by, and the workspace it sources.  The robot's own layout
#: (/home/robot/onboard/<dir>), which the offboard container reproduces with a symlink.
ROBOT_EXTRAS_PATH = f"/home/robot/onboard/extras/src/{PACKAGE}/urdf/clearpath_extras.urdf.xacro"
ROBOT_WORKSPACE = "/home/robot/onboard/extras/install/setup.bash"


def _workspace_root() -> Path | None:
    for candidate in REPO.parents:
        if (candidate / "workspace.repos").is_file():
            return candidate
    return None


def _sibling(relpath: str) -> Path:
    root = _workspace_root()
    if root is None:
        pytest.skip("not inside the clearpath workspace (no workspace.repos above this repo)")
    path = root / relpath
    if not path.is_file():
        pytest.fail(
            f"{relpath} is missing although the workspace root {root} is right there -- vcs import, or the file moved."
        )
    return path


@pytest.fixture(scope="session")
def extras_text() -> str:
    return EXTRAS.read_text(encoding="utf-8")


def _tool(name: str) -> str:
    return (EXTRAS.parent / "tools" / f"{name}.urdf.xacro").read_text(encoding="utf-8")


def _macro(name: str) -> str:
    """The tool itself, hung on a parent: what the a200's tool file and MARWIN 5's changer both call."""
    return (EXTRAS.parent / f"{name}.macro.xacro").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", XACROS, ids=lambda p: p.name)
def test_every_file_is_well_formed_xml(path):
    """The `--` trap included: ElementTree rejects it exactly as expat does inside xacro."""
    ET.fromstring(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", XACROS, ids=lambda p: p.name)
def test_every_mesh_uri_names_a_file_this_package_ships(path):
    """A package:// URI that points at a package which does not carry the file fails silently, in the viewer."""
    own = path.relative_to(REPO / "src").parts[0]
    for package, relpath in re.findall(r'filename="package://([^/]+)/([^"]+)"', path.read_text(encoding="utf-8")):
        assert package == own, f"package://{package} is not {own}; who installs {relpath}?"
        assert (REPO / "src" / package / relpath).is_file(), f"package://{package}/{relpath} does not exist here"


def test_the_end_effector_is_an_argument_whose_default_is_the_rg6(extras_text):
    """The robot's own hand unless the offboard mock asks for another; every name has its file."""
    assert '<xacro:arg name="end_effector" default="rg6"/>' in extras_text
    assert '<xacro:include filename="tools/$(arg end_effector).urdf.xacro"/>' in extras_text
    assert {p.name for p in TOOLS} >= {"rg6.urdf.xacro", "key_holder.urdf.xacro"}


def test_the_gripper_macro_is_included_from_the_package_that_owns_it():
    """The one cross-package dependency, and it must run this way round: assembly includes component."""
    assert "$(find rg6_description)/urdf/onrobot_rg_upstream.urdf.xacro" in _macro("rg6")
    manifest = (REPO / "src" / PACKAGE / "package.xml").read_text(encoding="utf-8")
    assert "<exec_depend>rg6_description</exec_depend>" in manifest, (
        "the include is there but the dependency is not declared -- colcon and rosdep cannot see it"
    )


@pytest.mark.parametrize("name", ["aruco_marker", "husky_top_assembly"])
def test_the_platform_keeps_the_links_the_stack_addresses_by_name(extras_text, name):
    assert f'<link name="{name}"' in extras_text


@pytest.mark.parametrize("path", TOOLS, ids=lambda p: p.name)
def test_every_tool_carries_the_link_robot_yaml_hangs_the_camera_on(path):
    """robot.yaml names one camera parent for every tool; a tool without it leaves the camera unattached."""
    assert '<link name="rg6_onrobot_rg6_base_link"' in path.read_text(encoding="utf-8")


def test_the_rg6_keeps_its_tcp():
    """The TCP every calibrated quantity is expressed against, and the MTC grasp planner's frame."""
    assert '<link name="rg6_hand_tcp"' in _macro("rg6")


def test_the_arch_carries_collision_geometry_and_a_mass(extras_text):
    """R15 and R47 in one link: without the boxes move_group plans through the arch, without the mass it weighs 0.1
    kg."""
    arch = extras_text.split('<link name="husky_top_assembly">', 1)[1].split("</link>", 1)[0]
    assert arch.count("<collision>") == 6, "the six boxes along the real structure"
    assert "<inertial>" in arch and 'value="6.21"' in arch


def test_the_package_installs_the_two_directories_the_uris_resolve_through():
    cmake = (REPO / "src" / PACKAGE / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "DIRECTORY urdf meshes" in cmake
    assert "DESTINATION share/${PROJECT_NAME}" in cmake


def test_robot_yaml_addresses_this_file_and_sources_this_workspace():
    """The SSOT in setup/, and the seam this move actually turns on."""
    import yaml

    robot_yaml = yaml.safe_load(_sibling("onboard/setup/config/robot.yaml").read_text(encoding="utf-8"))
    assert robot_yaml["platform"]["extras"]["urdf"]["path"] == ROBOT_EXTRAS_PATH
    workspaces = robot_yaml["system"]["ros2"]["workspaces"]
    assert ROBOT_WORKSPACE in workspaces, (
        f"{ROBOT_WORKSPACE} is not in system.ros2.workspaces -- the generator would find the file and then fail "
        f"on $(find rg6_description) resp. leave package://{PACKAGE} unresolvable"
    )


MARWIN_TOOLED = REPO / "src" / "marwin_extras_description" / "urdf" / "marwin5_tooled.urdf.xacro"


@pytest.mark.parametrize(("tool", "tcp"), [("rg6", "rg6_hand_tcp"), ("key_holder", "key_tip")])
def test_every_tool_the_changer_offers_is_a_macro_with_its_tcp(tool, tcp):
    """MARWIN 5's changer calls the same macro the a200 does, and names the TCP that macro defines."""
    tooled = MARWIN_TOOLED.read_text(encoding="utf-8")
    assert f"$(find {PACKAGE})/urdf/{tool}.macro.xacro" in tooled
    assert f"{tool}='{tcp}'" in tooled, f"the tool map names another TCP for {tool}"
    assert f'<link name="{tcp}"' in _macro(tool)
