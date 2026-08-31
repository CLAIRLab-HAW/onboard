#!/usr/bin/env python3
"""urdf_physics_patch: puts physical properties into descriptions that ship without them.

The robot's URDF is assembled from apt packages at every boot, and three of the things a physics engine needs are
simply not in them:

  * the six UR joints carry ``<dynamics damping="0" friction="0"/>`` -- hard-coded in ``ur_macro.xacro``, with no
    parameter and no yaml behind it;
  * the four wheel joints carry no ``<dynamics>`` at all;
  * ``top_plate_link`` carries a collision mesh and no ``<inertial>``, so whatever loads it has to invent a mass.

None of the three has a lever in ``robot.yaml``: ``clearpath_config`` does not model joint dynamics, and the two
descriptions come from ``packages.ros.org`` resp. ``packages.clearpathrobotics.com``.  That is the same situation
that produced ``rg6_moveit_patch`` (onrobot-rg6) for the SRDF, and the answer is the same shape -- patch after the
package, before the generator, idempotently, with a backup.

WHAT IS DIFFERENT FROM THE SRDF PATCH, and it decides the whole design: the SRDF is generated FLAT, so a fragment can
be appended before ``</robot>``.  The URDF is not.  There is no ``/clearpath/robot.urdf``; there is a 2,5 kB
``robot.urdf.xacro`` wrapper that pulls in the package macros and is expanded at launch.  Appending is therefore
useless -- you cannot override an existing joint's dynamics by declaring it twice.  The edit has to land IN the
package macro, which is what ``clearpath_custom_setup.py`` already does for the sensor mesh URIs and the arm
joint_states remap.

WHY IT LIVES IN THIS REPO, next to ``clearpath_custom_setup.py`` and not next to ``rg6_moveit_patch``: not one of
its targets is a gripper part.  It edits the six UR joints, the four wheel joints and the a200 top plate -- the arm
and the platform, whose setup this repo owns.  ``rg6_moveit_patch`` writes a foreign file about ITS OWN subject (the
RG6's planning group and named postures); this one is a foreign subject as well, and the marker it leaves in an
apt-owned file names the repo that has to answer for the line.  The kinship is with the two package edits
``clearpath_custom_setup.py`` already makes -- the sensor mesh URIs and the arm joint_states remap -- so this is the
third of THAT family, not the second of the SRDF's.

THE VALUES ARE DELIBERATELY MISSING.  Every target below stands with ``fragment=None``, which means the tool reports
it and changes nothing.  That is not an unfinished state, it is the honest one: nobody has measured the viscous
damping or the Coulomb friction of this arm, and a joint damping invented to look plausible is indistinguishable
from a measured one the next time somebody reads the file.

The near miss worth writing down, because it will be proposed again: ``maniskill_robot.physics`` carries
``ARM_DAMPING = 100.0`` and looks like exactly the number wanted here.  It is not.  That is the derivative gain of a
``PDJointPosControllerConfig`` -- the drive's D term -- while ``<dynamics damping>`` is passive viscous drag inside
the joint.  Writing the one into the other does not transfer a value, it ADDS 100 N*m*s/rad of drag underneath a
drive that was tuned without it; and that module's own header says moving those numbers invalidates every gate
measurement taken against them.  Its ``PAD_*_FRICTION`` are surface properties, for which URDF has no element at
all.  The only URDF-shaped pair over there, ``PassiveControllerConfig(damping=0.0, friction=0.0)``, is zero -- it
confirms the state below rather than changing it.  R47 carries the measurement.

Invocations:
  Robot:    from clearpath_custom_setup.py (per boot, before clearpath-robot-generate)
  Offboard: husky-offboard entrypoint.sh, before the generate_* runs
  Manual:   urdf_physics_patch --dry-run

Self-contained: needs only python3 (no ROS environment, no PyYAML) -- the robot runs it as a root-owned copy in
/usr/local/bin (the installer places it, like every other script here), and the offboard container copies the same
one file out of this repo at build time.  One file is the whole point: both deployments are a copy, not a build.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

TAG = "urdf_physics_patch"

#: Written next to every element this tool touches, so that a reader of an apt-owned file can see at a glance where
#: the line came from.  No double dash inside: XML forbids it in a comment.
MARKER = "<!-- husky-custom-setup:urdf_physics_patch -->"

#: Where the ROS packages live.  A glob rather than a fixed distro, because the same tool runs on the robot (jazzy
#: from apt) and in the container (jazzy from the image), and a hard-coded ``jazzy`` would fail silently on the day
#: one of them moves.
ROS_SHARE_GLOB = "/opt/ros/*/share"


class Target:
    """One element that has to gain, or keep, a physical property.

    :param package: ROS package the description belongs to.
    :param relpath: file inside the package's share directory.
    :param element: ``joint`` or ``link`` -- what carries the property.
    :param name: the ``name=`` attribute VERBATIM as the xacro writes it, ``${...}`` substitutions included.  The
        file is not expanded here, so the literal is what has to match.
    :param child: tag of the property element (``dynamics``, ``inertial``).
    :param fragment: the XML to write, or ``None`` when the value has not been measured -- then the target is
        reported and skipped, never guessed.
    :param why: what the value would be for, and what it costs to be missing.  Printed with a skip, so the log says
        which measurement is outstanding rather than just a count.
    """

    def __init__(self, package, relpath, element, name, child, fragment, why):
        self.package = package
        self.relpath = relpath
        self.element = element
        self.name = name
        self.child = child
        self.fragment = fragment
        self.why = why

    def __str__(self):
        return f"{self.package}/{self.relpath} {self.element} {self.name} <{self.child}>"


#: The six UR joints.  ``ur_macro.xacro`` writes ``<dynamics damping="0" friction="0"/>`` into each of them, so the
#: element is already there and a value would REPLACE it rather than be inserted.  Zero damping is not a neutral
#: default: MuJoCo integrates a position-driven joint with no passive damping into an oscillation, and PhysX carries
#: the whole resistance in the drive, which is why the ManiSkill route had to tune a D gain that a damped model would
#: not need.  Measuring it is R47.
_UR_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow",
    "wrist_1",
    "wrist_2",
    "wrist_3",
)

TARGETS = [
    Target(
        package="ur_description",
        relpath="urdf/ur_macro.xacro",
        element="joint",
        name="${tf_prefix}" + f"{joint}_joint",
        child="dynamics",
        # No measurement exists.  See the module docstring for why the ManiSkill controller gains are not one.
        fragment=None,
        why="viscous damping and Coulomb friction of the UR5 joint (R47)",
    )
    for joint in _UR_JOINTS
]

TARGETS += [
    #: Both wheel variants, because which one is fitted is decided in robot.yaml and this tool does not read it.
    #: Patching the variant that is not built costs nothing; missing the one that is would be silent.
    Target(
        package="clearpath_platform_description",
        relpath=f"urdf/a200/drivetrain/wheels/{variant}.urdf.xacro",
        element="joint",
        name="${prefix}_wheel_joint",
        child="dynamics",
        fragment=None,
        why=f"rolling resistance of the {variant} wheel (R47)",
    )
    for variant in ("outdoor", "indoor")
]

TARGETS.append(
    #: ``top_plate_link`` carries a collision mesh and no mass.  ``twinlink.urdf_mujoco._ensure_inertial`` substitutes
    #: 0,1 kg for it, the same silent stand-in that husky_top_assembly got until its own inertial was derived.  Here
    #: the geometry alone does not settle it: the plate is sheet metal, and a solid mesh at any density overstates it.
    Target(
        package="clearpath_platform_description",
        relpath="urdf/a200/attachments/top_plate.urdf.xacro",
        element="link",
        name="${name}_link",
        child="inertial",
        fragment=None,
        why="mass and inertia of the a200 top plate (R47)",
    )
)


def log(msg, err=False):
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def atomic_write(path, content):
    """Write ``content`` over ``path``, keeping one backup and never leaving a half-written file.

    The same shape as ``rg6_moveit_patch.atomic_write``: the backup is taken ONCE, so a second run cannot overwrite
    the pristine apt copy with an already-patched one.
    """
    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        log(f"backup written: {backup}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def element_spans(content, element, name):
    """Character ranges of every ``<element name="NAME"> ... </element>`` in ``content``.

    String surgery rather than an XML round trip, and for the same reason ``rg6_moveit_patch`` does it: these are
    files this workspace does not own.  Rewriting them through ElementTree would reformat every untouched line and
    drop the upstream comments, which turns the ``.bak`` diff -- the only way to see what a boot changed -- into
    noise.  Well-formedness is checked afterwards, on the result.

    ALL of them, not the first: a macro may define the same link under several ``<xacro:if>`` branches -- the a200
    top plate does, once per plate model -- and patching only the branch that happens to come first would land the
    property in the variant that is not fitted, silently.

    :returns: list of ``(start, end)``, ``end`` at the start of the closing tag; empty if the element is absent.
    :raises ValueError: if the element does not close, or nests one of its own kind (which would make the naive
        search for the closing tag pick the wrong one).
    """
    spans = []
    for opening in re.finditer(rf"<{element}\s[^>]*name=\"{re.escape(name)}\"[^>]*>", content):
        closing = content.find(f"</{element}>", opening.end())
        if closing < 0:
            raise ValueError(f"{element} {name!r} does not close")
        if re.search(rf"<{element}\s", content[opening.end() : closing]):
            raise ValueError(f"{element} {name!r} contains a nested <{element}> -- the span cannot be trusted")
        spans.append((opening.end(), closing))
    return spans


def apply_target(content, target):
    """Insert or refresh ``target``'s property element inside its named element.

    Every occurrence of the named element, and from the back forwards so that an earlier span's offsets survive a
    later span's edit.

    :returns: ``(content, action)`` -- action is one of ``inserted``, ``refreshed``, ``unchanged``, ``absent``.
    """
    spans = element_spans(content, target.element, target.name)
    if not spans:
        return content, "absent"

    actions = set()
    for start, end in reversed(spans):
        body = content[start:end]

        # The indentation of the line the closing tag sits on, so an inserted block lands where a human would put it.
        trailing = re.search(r"\n([ \t]*)$", body)
        indent = (trailing.group(1) if trailing else "  ") + "  "
        block = f"{MARKER}\n{indent}{target.fragment}"

        # Two branches, the self-closing one first: ``<child .../>`` OR ``<child ...>...</child>``.  A single
        # ``.*?`` in front of the alternation cannot express that -- non-greedy stops at the FIRST ``/>``, which
        # inside a nested element is one of its children.  Measured 2026-08-31 on the top plate's own target: after
        # inserting a four-element ``<inertial>`` (141 characters), a second run matched the 33 up to the inner
        # ``<origin/>``, reported "refreshed" and produced a mismatched tag that the well-formedness gate then
        # refused to write.  ``[^>]*`` is what keeps a branch from crossing the opening tag's own ``>``.
        pattern = rf"[ \t]*(?:{re.escape(MARKER)}\s*)?<{target.child}\b(?:[^>]*/>|[^>]*>.*?</{target.child}>)"
        existing = re.search(pattern, body, re.S)
        if existing is None:
            stripped = body.rstrip(" \t")
            new_body = stripped + indent + block + "\n" + body[len(stripped) :]
            actions.add("inserted")
        elif existing.group(0).strip() == block.strip():
            actions.add("unchanged")
            continue
        else:
            new_body = body[: existing.start()] + indent + block + body[existing.end() :]
            actions.add("refreshed")
        content = content[:start] + new_body + content[end:]

    if actions == {"unchanged"}:
        return content, "unchanged"
    return content, "/".join(sorted(actions - {"unchanged"}))


def patch_file(path, targets, dry_run):
    """Apply every target that belongs to ``path``.

    :returns: number of elements actually changed.
    """
    with open(path) as f:
        original = f.read()

    content = original
    for target in targets:
        try:
            content, action = apply_target(content, target)
        except ValueError as e:
            log(f"WARN: {target}: {e} -- skipped.", err=True)
            continue
        if action == "absent":
            log(f"WARN: {target}: no such {target.element} in {path} -- upstream renamed it?", err=True)
        elif action != "unchanged":
            log(f"{target}: {action}.")

    if content == original:
        return 0
    try:
        ET.fromstring(content)
    except ET.ParseError as e:
        log(f"ERROR: the patched {path} is not well-formed ({e}) -- nothing written.", err=True)
        return 0
    if dry_run:
        log(f"dry run: {path} would change.")
        return 1
    atomic_write(path, content)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ros-share",
        default=ROS_SHARE_GLOB,
        help=f"glob of the ROS share directories to patch in (default: {ROS_SHARE_GLOB})",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args()

    log(f"start (share: {args.ros_share}).")

    pending = [t for t in TARGETS if t.fragment is None]
    for target in pending:
        log(f"no measured value for {target} -- {target.why}; left as upstream ships it.")

    by_file = {}
    for target in TARGETS:
        if target.fragment is None:
            continue
        for share in glob.glob(args.ros_share):
            path = os.path.join(share, target.package, target.relpath)
            if os.path.isfile(path):
                by_file.setdefault(path, []).append(target)

    if not by_file:
        log(f"nothing to write: {len(pending)} of {len(TARGETS)} targets are waiting for a measurement.")
        return 0

    changed = sum(patch_file(path, targets, args.dry_run) for path, targets in sorted(by_file.items()))
    log(f"done ({changed} file(s) changed, {len(pending)} target(s) still without a value).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
