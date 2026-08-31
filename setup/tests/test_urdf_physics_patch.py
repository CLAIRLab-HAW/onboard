"""The patcher for the physical properties the apt descriptions ship without.

Every target it carries stands without a value on purpose (see the tool's docstring: nobody has measured the UR
joints, and the ManiSkill controller gains are a different quantity).  So the shipped configuration exercises only
the skip path, and a tool whose writing half has never run is a tool that breaks the first time somebody fills a
value in.  These tests fill values in.

They run against COPIES of the real upstream files where those are available in the workspace bundle -- the point is
not that the patcher can edit some XML, it is that it can edit ``ur_macro.xacro`` as UR actually writes it, with the
``<xacro:if>`` blocks and the ``${tf_prefix}`` literals in place.  Synthetic fixtures cover the edges that the real
files do not happen to contain.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parent.parent / "scripts/urdf_physics_patch"
_spec = importlib.util.spec_from_loader(
    "urdf_physics_patch", importlib.machinery.SourceFileLoader("urdf_physics_patch", str(_TOOL))
)
patch = importlib.util.module_from_spec(_spec)
sys.modules["urdf_physics_patch"] = patch
_spec.loader.exec_module(patch)

#: The workspace's copy of the generated bundle's source packages -- ``robot/<repo>/tests/`` is three
#: levels below the workspace root.  Absent in a bare checkout of this repo, and then every test that
#: reads a real upstream file skips itself by name.
BUNDLE = Path(__file__).resolve().parents[3] / "urdf"

DAMPING = '<dynamics damping="0.5" friction="0.2"/>'


def _target(package, relpath, element, name, child, fragment=DAMPING):
    return patch.Target(package, relpath, element, name, child, fragment, "test")


# ---- against the real upstream files --------------------------------------------------------------------------


@pytest.fixture()
def ur_macro() -> str:
    path = BUNDLE / "ur_description/urdf/ur_macro.xacro"
    if not path.is_file():
        pytest.skip(f"no bundle copy at {path}")
    return path.read_text()


def test_it_replaces_the_zero_dynamics_ur_ships(ur_macro):
    """The UR joints already HAVE a ``<dynamics>``; a value has to replace it, not land beside it."""
    out, action = patch.apply_target(
        ur_macro, _target("ur_description", "urdf/ur_macro.xacro", "joint", "${tf_prefix}elbow_joint", "dynamics")
    )
    assert action == "refreshed"
    assert DAMPING in out
    # The five other joints keep theirs: an anchor that matched them all would be worse than one that matched none.
    assert out.count('<dynamics damping="0" friction="0"/>') == 5


def test_it_leaves_the_rest_of_the_file_alone(ur_macro):
    """A patcher on a file this workspace does not own has to touch the one line and nothing else.

    Counted as a diff rather than line by line: an inserted line shifts everything after it, so a positional
    comparison calls the whole remainder of the file changed and proves nothing.
    """
    import difflib

    out, _ = patch.apply_target(
        ur_macro, _target("ur_description", "urdf/ur_macro.xacro", "joint", "${tf_prefix}wrist_2_joint", "dynamics")
    )
    changed = [
        line
        for line in difflib.unified_diff(ur_macro.splitlines(), out.splitlines(), n=0, lineterm="")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    # One line out (upstream's zero dynamics), two in (the marker and ours).  Nothing else.
    assert len(changed) == 3, f"the edit is not confined to the one element: {changed}"
    assert changed[0] == '-      <dynamics damping="0" friction="0"/>'
    assert patch.MARKER in changed[1] and DAMPING in changed[2]


def test_it_is_idempotent_on_the_real_file(ur_macro):
    once, _ = patch.apply_target(
        ur_macro, _target("ur_description", "urdf/ur_macro.xacro", "joint", "${tf_prefix}elbow_joint", "dynamics")
    )
    twice, action = patch.apply_target(
        once, _target("ur_description", "urdf/ur_macro.xacro", "joint", "${tf_prefix}elbow_joint", "dynamics")
    )
    assert action == "unchanged"
    assert twice == once


def test_it_inserts_where_upstream_has_no_dynamics_at_all():
    """The wheel joints carry none, so this is the insert path rather than the replace path."""
    path = BUNDLE / "clearpath_platform_description/urdf/a200/drivetrain/wheels/outdoor.urdf.xacro"
    if not path.is_file():
        pytest.skip(f"no bundle copy at {path}")
    content = path.read_text()
    assert "<dynamics" not in content, "upstream gained a <dynamics> -- this test's premise is gone"
    out, action = patch.apply_target(
        content, _target("clearpath_platform_description", "x", "joint", "${prefix}_wheel_joint", "dynamics")
    )
    assert action == "inserted"
    assert DAMPING in out


def test_it_patches_every_branch_of_the_top_plate():
    """``${name}_link`` is defined once per plate model; the fitted one is chosen at generate time, not here."""
    path = BUNDLE / "clearpath_platform_description/urdf/a200/attachments/top_plate.urdf.xacro"
    if not path.is_file():
        pytest.skip(f"no bundle copy at {path}")
    content = path.read_text()
    branches = content.count('<link name="${name}_link">')
    assert branches > 1, "the top plate has stopped having several model branches -- the test's premise is gone"
    inertial = (
        '<inertial><mass value="4.0"/><inertia ixx="0.1" iyy="0.1" izz="0.1" ixy="0" ixz="0" iyz="0"/></inertial>'
    )
    out, action = patch.apply_target(
        content, _target("clearpath_platform_description", "x", "link", "${name}_link", "inertial", inertial)
    )
    assert action == "inserted"
    assert out.count(inertial) == branches


# ---- the edges the real files do not contain -------------------------------------------------------------------


def test_an_absent_element_is_reported_not_invented():
    out, action = patch.apply_target(
        '<robot><joint name="other"></joint></robot>', _target("p", "f", "joint", "${tf_prefix}elbow_joint", "dynamics")
    )
    assert action == "absent"
    assert out == '<robot><joint name="other"></joint></robot>'


def test_an_unclosed_element_is_refused():
    with pytest.raises(ValueError, match="does not close"):
        patch.element_spans('<robot><joint name="j" type="revolute">', "joint", "j")


def test_a_nested_element_of_the_same_kind_is_refused():
    """The closing tag is found by search, so a nested one would silently end the span in the wrong place."""
    content = '<robot><joint name="outer"><joint name="inner"></joint></joint></robot>'
    with pytest.raises(ValueError, match="nested"):
        patch.element_spans(content, "joint", "outer")


def test_a_changed_value_refreshes_rather_than_duplicates():
    content = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    once, _ = patch.apply_target(content, _target("p", "f", "joint", "j", "dynamics"))
    other = _target("p", "f", "joint", "j", "dynamics", '<dynamics damping="9.0"/>')
    twice, action = patch.apply_target(once, other)
    assert action == "refreshed"
    assert twice.count("<dynamics") == 1
    assert 'damping="9.0"' in twice


def test_the_marker_survives_a_refresh():
    """Without the marker a reader of an apt file cannot tell our line from upstream's."""
    content = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    out, _ = patch.apply_target(content, _target("p", "f", "joint", "j", "dynamics"))
    assert out.count(patch.MARKER) == 1
    again, _ = patch.apply_target(out, _target("p", "f", "joint", "j", "dynamics", '<dynamics damping="9.0"/>'))
    assert again.count(patch.MARKER) == 1


def test_the_result_stays_well_formed_xml():
    import xml.etree.ElementTree as ET

    content = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    out, _ = patch.apply_target(content, _target("p", "f", "joint", "j", "dynamics"))
    ET.fromstring(out)


def test_a_file_that_would_break_is_not_written(tmp_path, capsys):
    """The well-formedness gate: a fragment that does not close must leave the file as it was."""
    path = tmp_path / "broken.urdf.xacro"
    original = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    path.write_text(original)
    bad = _target("p", "f", "joint", "j", "dynamics", "<dynamics damping='1'>")
    assert patch.patch_file(str(path), [bad], dry_run=False) == 0
    assert path.read_text() == original
    assert not (tmp_path / "broken.urdf.xacro.bak").exists()
    assert "not well-formed" in capsys.readouterr().err


def test_the_backup_is_taken_once_and_keeps_the_pristine_copy(tmp_path):
    """A second run must not overwrite the apt original with an already-patched file."""
    path = tmp_path / "f.urdf.xacro"
    original = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    path.write_text(original)
    patch.patch_file(str(path), [_target("p", "f", "joint", "j", "dynamics")], dry_run=False)
    patch.patch_file(
        str(path), [_target("p", "f", "joint", "j", "dynamics", '<dynamics damping="9.0"/>')], dry_run=False
    )
    assert (tmp_path / "f.urdf.xacro.bak").read_text() == original


def test_a_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "f.urdf.xacro"
    original = '<robot>\n  <joint name="j">\n    <axis xyz="0 0 1"/>\n  </joint>\n</robot>'
    path.write_text(original)
    assert patch.patch_file(str(path), [_target("p", "f", "joint", "j", "dynamics")], dry_run=True) == 1
    assert path.read_text() == original


# ---- the shipped configuration ---------------------------------------------------------------------------------


def test_every_shipped_target_is_still_without_a_value():
    """The state R47 describes.  When somebody fills one in, this test is what tells them to update R47 too."""
    filled = [str(t) for t in patch.TARGETS if t.fragment is not None]
    assert not filled, f"these targets now carry a value -- close or amend R47: {filled}"


def test_every_shipped_target_names_the_measurement_it_waits_for():
    for target in patch.TARGETS:
        assert target.why, f"{target} does not say what measurement it needs"


def test_the_shipped_targets_cover_the_gaps_the_bundle_shows():
    """Ties the target list to the model: the six arm joints, both wheel variants, the top plate."""
    names = {(t.package, t.element, t.name) for t in patch.TARGETS}
    for joint in ("shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3"):
        assert ("ur_description", "joint", "${tf_prefix}" + f"{joint}_joint") in names
    assert ("clearpath_platform_description", "joint", "${prefix}_wheel_joint") in names
    assert ("clearpath_platform_description", "link", "${name}_link") in names
