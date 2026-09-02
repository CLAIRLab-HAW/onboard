#!/usr/bin/env python3
"""sensor_mesh_uri_patch: rewrites Clearpath's sensor mesh URIs from ``file://`` to ``package://``.

``clearpath_sensors_description`` references the Realsense meshes as ``file://$(find realsense2_description)/...``
-- unlike upstream ``realsense2_description`` itself, which writes ``package://realsense2_description/...``
(``_d435.urdf.xacro``:78).  Only those four intel xacros deviate.

DO NOT REMOVE -- this is not a transitional workaround.  Upstream never fixed the URIs; checked on the a200-0553 on
2026-08-20 by unpacking and reading both .deb files:

    2.9.8  (packages.ros.org)               -> file://, all four intel xacros
    2.9.15 (packages.clearpathrobotics.com) -> file://, all four

Two probes that can NOT settle this, even though they look as if they could:

  * "the URDF builds without error" -- xacro substitutes ``$(find ...)`` and writes text, it never opens a mesh.
    Even a completely made-up ``package://`` passes with exit 0 and empty stderr.
  * "the mesh is visible in Foxglove" -- that shows the state AFTER the last patcher run.  The patch is persistent:
    it writes into the package files, and they stay written until dpkg overwrites them.

What counts is solely what is inside the .deb.

WHY IT MATTERS AT ALL: not the resource_retriever -- that can do ``file://`` -- but the ``asset_uri_allowlist`` of
the foxglove_bridge, which starts with ``^package://`` and rejects everything else before the retriever ever sees
it.  Measured 2026-08-14 via fetchAsset (foxglove_bridge 3.4.1, subprotocol foxglove.sdk.v1):
``package://realsense2_description/meshes/d435.dae`` -> status 0, 15782439 bytes; the same file as ``file://`` ->
status 1, "Failed to retrieve asset".  RViz reads the local file directly and does not care either way, and the
``<collision>`` is a box primitive -- so planning, collision checking and the self filter are untouched and the
effect is purely visual (the camera model in Foxglove's 3D panel).  Context: R25 in the ROBOTER-TODO archive.

WHY THE TWO DEPLOYMENTS NEED THE SAME FILE, which is what put this in a script of its own: the robot generates its
URDF at every boot from apt packages that an update can roll back, so it re-applies the fix per boot; the offboard
container generates one of its own from a robot.yaml fetched off the same repo.  A difference between any two of
those generated URDFs must never be explainable by "the fix ran on one side and not the other" -- and while the
logic lived twice (a function in ``clearpath_custom_setup.py``, a heredoc in the husky-offboard Dockerfile), the
only way to know they still agreed was to read both.

Invocations:
  Robot:    from clearpath_custom_setup.py (per boot, after clearpath-robot-generate, before the consumers start)
  Offboard: husky-offboard Dockerfile, at BUILD time -- apt does not run again afterwards, so once is enough
  Manual:   sensor-mesh-uri-patch --dry-run

Self-contained: needs only python3 (no ROS environment, no PyYAML) -- the robot runs it as a root-owned copy in
/usr/local/bin (the installer places it, like every other script here), and the offboard image copies the same one
file out of this repo.  One file is the whole point: both deployments are a copy, not a build.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile

TAG = "sensor_mesh_uri_patch"

#: The sensor mesh URI as Clearpath ships it, and what it has to become.  The package NAME is part of the anchor,
#: not just the ``file://`` scheme: ``rg6_description`` writes its meshes the same way and must be left alone.
MESH_URI_OLD = "file://$(find realsense2_description)"
MESH_URI_NEW = "package://realsense2_description"

#: Where the ROS packages live.  A glob rather than a fixed distro, for the same reason as in
#: ``urdf_physics_patch``: the same tool runs on the robot (jazzy from apt) and in the container (jazzy from the
#: image), and a hard-coded ``jazzy`` would fail silently on the day one of them moves.
ROS_SHARE_GLOB = "/opt/ros/*/share"

#: The xacros to search, relative to one share directory.  ``*.urdf.xacro`` and not ``*`` also decides that a
#: ``.bak`` from an earlier run is not itself a target -- otherwise the backup would be patched along with the file
#: and stop being a record of the state before.
XACRO_RELGLOB = "clearpath_sensors_description/urdf/**/*.urdf.xacro"


def log(msg, err=False):
    """Log line (stdout/stderr); captured by journald via SyslogIdentifier on the robot."""
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def atomic_write(path, content):
    """Write ``content`` over ``path``, keeping one backup and never leaving a half-written file.

    The same shape as ``urdf_physics_patch.atomic_write``: the backup is taken ONCE, so a second run cannot
    overwrite the pristine apt copy with an already-patched one.  The diff against that copy is the only way to see
    what a boot changed.  One deviation from that shape: a backup that cannot be written does not stop the rewrite
    -- the fix outranks the undo record.
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
    """Swap every occurrence in one xacro.

    :returns: ``"changed"`` if the file carried the old URI (and was, or would have been, rewritten), ``"clean"``
        if it did not, ``"failed"`` if it could not be read or rewritten.
    """
    try:
        with open(path) as f:
            content = f.read()
    except OSError as e:
        # Skipped rather than fatal, so the run still reports the files it DID reach -- but the patch this one was
        # meant to receive never lands, hence stderr and the nonzero exit in main().
        log(f"cannot read {path}, skipping: {e}", err=True)
        return "failed"
    if MESH_URI_OLD not in content:
        return "clean"
    if dry_run:
        log(f"dry run: {path} would change.")
        return "changed"
    try:
        atomic_write(path, content.replace(MESH_URI_OLD, MESH_URI_NEW))
    except OSError as e:
        log(f"cannot write {path}: {e}", err=True)
        return "failed"
    return "changed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ros-share",
        default=ROS_SHARE_GLOB,
        help=f"glob of the ROS share directories to patch in (default: {ROS_SHARE_GLOB})",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args(argv)

    files = sorted(
        path
        for share in glob.glob(args.ros_share)
        for path in glob.glob(os.path.join(share, XACRO_RELGLOB), recursive=True)
    )

    # The two ways of finding nothing are NOT the same thing, and conflating them is what made the old message
    # ("no file:// mesh found") unreadable: with the package present, zero hits is the steady state the boot
    # service reaches after its first run; with no xacro at all, the package is gone or upstream moved the path.
    # The nonzero exit is what makes the loss loud where it can still be caught -- it fails the offboard image
    # build, while the boot service (run_root_tool) only logs it and carries on.
    if not files:
        log(f"WARN: no sensor xacro under {args.ros_share}/{XACRO_RELGLOB} -- package missing or moved?", err=True)
        return 1

    results = [(os.path.basename(p), patch_file(p, args.dry_run)) for p in files]
    changed = [name for name, result in results if result == "changed"]
    failed = [name for name, result in results if result == "failed"]
    if changed:
        did = "would set package:// in" if args.dry_run else "package:// set in"
        log(f"{did}: {', '.join(changed)} ({len(files)} xacros checked).")
    elif not failed:
        log(f"already package:// -- no change ({len(files)} xacros checked).")
    if failed:
        log(f"failed to patch: {', '.join(failed)} -- mesh URIs there may still be file://.", err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
