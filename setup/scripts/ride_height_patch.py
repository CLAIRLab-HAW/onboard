#!/usr/bin/env python3
"""ride_height_patch: puts THIS vehicle's loaded tyre radius into the a200 description.

``base_footprint`` is the ground reference of the whole workspace -- every calibrated height is measured against
it -- and Clearpath derives it from the NOMINAL wheel radius:

    <origin xyz="0 0 ${wheel_vertical_offset - front_wheel_radius}" .../>   =  0.03282 - 0.1651  =  -0.13228

That is a rigid vehicle on undeflected tyres.  This one carries a UR5 with an RG6 on its front plate, and the tyres
deflect under that mass: the deck measures ~330 mm above ground where the nominal model says 363.

MEASURED 2026-09-01 at the real a200-0553, twice, on two separate descents about an hour apart: the closed gripper
was jogged onto the floor by hand and TF read against ``base_footprint``.  The identical contact stood at 113.0 mm
under the nominal model and at 81.0 mm once the 31 mm were applied -- a 32.0 mm difference against the 31.0 mm
applied, so the number is confirmed to within a millimetre by a measurement independent of the one that produced
it.  Cross-check on the same touch: ``rg6_gripper_grasp_frame`` (the pad centre with the hand closed) sat at
23.0 mm, half a pad height, so the pad underside met the floor at exactly z = 0.

WHY IT HAS TO BE THE RIDE HEIGHT AND NOT THE DECK MOUNT, which is the whole reason this tool exists: tyre squish
lowers the entire vehicle towards the GROUND.  It does not shorten the distance between the chassis and the top
plate.  Expressing the same 31 mm as a ``top_plate`` offset in robot.yaml drives the superstructure INTO the
chassis and the wheels, and that is not a cosmetic difference -- measured on the robot on 2026-09-01, move_group's
``check_state_validity`` then answers ``valid=False`` for EVERY state, with ``husky_top_assembly`` 25.78 mm inside
``base_link``.  A permanent self-collision means every plan is refused with START_STATE_IN_COLLISION.  In the
MuJoCo twin the same formulation shows as ``base_link`` vs ``arm_0_shoulder_link`` (-3.64 mm) and ``top_plate_link``
vs all four wheels (-4.92 mm), and it took 22 of hrl's tests down; moving the same 31 mm here left 4, three of them
frozen model pins that any geometry change has to re-cut anyway.

NO LEVER IN robot.yaml: ``clearpath_config`` models mounts and sensors, not the ground reference -- the offset is
computed inside ``a200.urdf.xacro`` from two xacro properties.  Same situation, same answer as
``urdf_physics_patch`` and ``sensor_mesh_uri_patch``: patch the package after apt, before the generator,
idempotently, with a backup.  It is NOT part of ``urdf_physics_patch`` on purpose -- that tool is about physical
properties a physics engine needs (joint dynamics, inertials) and deliberately carries no measured values; this is
geometry, and it carries one.

AN UPGRADE WILL NOT MAKE THIS UNNECESSARY.  Checked 2026-09-01 by downloading and unpacking the newer .deb:

    2.9.5  (installed)                      -> ${wheel_vertical_offset - front_wheel_radius}
    2.9.15 (packages.clearpathrobotics.com) -> identical, byte for byte

Across the whole package only one a200 line differs between the two (the ``control`` default, ``diff_fwd`` ->
``diff_4wd``, which robot.yaml sets explicitly anyway) and not a single ``.stl`` -- the A200 collision geometry is
untouched.  That is also the expectation: how far THIS vehicle's tyres deflect under THIS payload is a property of
our build, not of the product, so upstream has no reason to ever carry it.

Invocations:
  Robot:    from clearpath_custom_setup.py (per boot, before clearpath-robot-generate)
  Offboard: husky-offboard entrypoint.sh, before the generate_* runs
  Manual:   ride-height-patch --dry-run

Self-contained: needs only python3 (no ROS environment, no PyYAML) -- the robot runs it as a root-owned copy in
/usr/local/bin (the installer places it, like every other script here), and the offboard container copies the same
one file out of this repo at build time.  One file is the whole point: both deployments are a copy, not a build.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile

TAG = "ride_height_patch"

#: Tyre deflection under the UR5 + RG6 payload (m), measured 2026-09-01 -- see the module docstring for the two
#: descents behind it.  It is subtracted from the NOMINAL radius, which is what "loaded radius" means: the wheel
#: centre sits this much closer to the ground than an undeflected tyre would put it.
SQUISH_M = 0.031

#: The ``base_footprint`` origin exactly as Clearpath ships it, and what it has to become.  Anchoring on the whole
#: attribute rather than on the expression alone keeps ``${front_wheel_radius * 2}`` (the ros2_control wheel
#: diameter, same file) out of reach -- that one describes the ROLLING radius for odometry, which deflection
#: changes differently and which is not this tool's subject.
ORIGIN_OLD = '<origin xyz="0 0 ${wheel_vertical_offset - front_wheel_radius}" rpy="0 0 0" />'
ORIGIN_NEW = f'<origin xyz="0 0 ${{wheel_vertical_offset - (front_wheel_radius - {SQUISH_M})}}" rpy="0 0 0" />'

#: Where the ROS packages live.  A glob rather than a fixed distro, for the same reason as in
#: ``urdf_physics_patch``: the same tool runs on the robot (jazzy from apt) and in the container (jazzy from the
#: image), and a hard-coded ``jazzy`` would fail silently on the day one of them moves.
ROS_SHARE_GLOB = "/opt/ros/*/share"

#: The one xacro that computes the ground reference.  ``.urdf.xacro`` and not ``*`` also decides that a ``.bak``
#: from an earlier run is not itself a target -- otherwise the backup would be patched along with the file and stop
#: being a record of the state before.
XACRO_RELGLOB = "clearpath_platform_description/urdf/a200/a200.urdf.xacro"


def log(msg, err=False):
    """Log line (stdout/stderr); captured by journald via SyslogIdentifier on the robot."""
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def atomic_write(path, content):
    """Write ``content`` over ``path``, keeping one backup and never leaving a half-written file.

    The same shape as ``sensor_mesh_uri_patch.atomic_write``: the backup is taken ONCE, so a second run cannot
    overwrite the pristine apt copy with an already-patched one.  The diff against that copy is the only way to see
    what a boot changed.  A backup that cannot be written does not stop the rewrite -- the fix outranks the undo
    record.
    """
    backup = path + ".bak"
    if not os.path.exists(backup):
        try:
            shutil.copy2(path, backup)
            log(f"backup written: {backup}")
        except OSError as e:
            # The write below goes ahead regardless, but without the .bak it cannot be undone -- hence stderr.
            log(f"no backup of {path}: {e}", err=True)
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


def patch_file(path, dry_run):
    """Swap the ``base_footprint`` origin in one xacro.

    :returns: ``"changed"`` if the file carried the nominal origin (and was, or would have been, rewritten),
        ``"clean"`` if the loaded radius is already in place, ``"failed"`` if it could not be read, rewritten, or
        if neither form was found (an upstream rewrite of the line -- silence there would drop the ride height
        back to nominal without anybody noticing).
    """
    try:
        with open(path) as f:
            content = f.read()
    except OSError as e:
        # Skipped rather than fatal, so the run still reports the files it DID reach -- but the patch this one was
        # meant to receive never lands, hence stderr and the nonzero exit in main().
        log(f"cannot read {path}, skipping: {e}", err=True)
        return "failed"
    if ORIGIN_NEW in content:
        return "clean"
    if ORIGIN_OLD not in content:
        log(
            f"{path}: neither the nominal nor the loaded base_footprint origin found -- upstream moved the line?",
            err=True,
        )
        return "failed"
    if dry_run:
        log(f"dry run: {path} would change.")
        return "changed"
    try:
        atomic_write(path, content.replace(ORIGIN_OLD, ORIGIN_NEW))
    except OSError as e:
        log(f"cannot write {path}: {e}", err=True)
        return "failed"
    return "changed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ros-share",
        default=ROS_SHARE_GLOB,
        help=f"glob of the ROS share directories to patch in (default: {ROS_SHARE_GLOB})",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args(argv)

    files = sorted(
        path for share in glob.glob(args.ros_share) for path in glob.glob(os.path.join(share, XACRO_RELGLOB))
    )
    # The two ways of finding nothing are NOT the same thing.  With the package present, zero hits is the steady
    # state the boot service reaches after its first run; with no xacro at all, the package is gone or upstream
    # moved the path -- and then base_footprint silently falls back to the nominal radius, which is the one error
    # this tool exists to prevent.  The nonzero exit fails the offboard image build, while the boot service
    # (run_root_tool) only logs it and carries on.
    if not files:
        log(f"WARN: no a200 xacro under {args.ros_share}/{XACRO_RELGLOB} -- package missing or moved?", err=True)
        return 1

    results = [(os.path.basename(p), patch_file(p, args.dry_run)) for p in files]
    changed = [name for name, result in results if result == "changed"]
    failed = [name for name, result in results if result == "failed"]
    if changed:
        did = "would set" if args.dry_run else "set"
        log(f"{did} the loaded wheel radius (-{SQUISH_M * 1000:.0f} mm) in: {', '.join(changed)}.")
    elif not failed:
        log(f"loaded wheel radius already in place -- no change ({len(files)} xacro(s) checked).")
    if failed:
        log(f"failed to patch: {', '.join(failed)} -- base_footprint there is the NOMINAL ground reference.", err=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
