# Changelog — husky-extras

What changed when. The current state is described in the [README](README.md).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
the versioning [Semantic Versioning](https://semver.org/).


## 2026-09-23 (the tools are macros)

- **`rg6.macro.xacro` and `key_holder.macro.xacro`**: each tool as a macro with
  a `parent` -- the face it is screwed onto. `tools/rg6.urdf.xacro` and
  `tools/key_holder.urdf.xacro` call it on `arm_0_tool0` and keep the a200's
  camera alias beside it; their expanded links and joints are identical to
  before (compared element by element). A robot with another flange -- MARWIN 5
  behind its tool changer -- calls the same macro.
- **The file tests read every xacro under `src/`**, the macros included; a
  `package://` URI must name the file's own package.

## 2026-09-23 (the end effector is an argument)

- **`end_effector` selects the tool** (xacro argument, default `rg6`):
  `clearpath_extras.urdf.xacro` includes `urdf/tools/<name>.urdf.xacro`. The
  RG6 block moved unchanged into `tools/rg6.urdf.xacro`; with the default the
  expanded description is the same as before. `robot.yaml` passes no argument.
- **`tools/key_holder.urdf.xacro`**: the Rittal key holder of the cabinet task,
  meshes from mujoco-mia under `meshes/key_holder/`, primitive collisions, TCP
  `key_tip`, and `rg6_onrobot_rg6_base_link` as an alias that puts the D435 on
  the holder, upright, on the flange's +y side. The holder sits turned half a
  turn on the flange. R61: placed, not measured.
- **The tests read every file**: well-formed XML and `package://` URIs per
  tool, the camera's parent in each; the RG6's own checks read its tool file.

## 2026-08-31 (the robot's own assembly gets a repo)

- **New repo, one package: `husky_extras_description`.** It holds
  `clearpath_extras.urdf.xacro` and `husky_sensor_arch.gltf`, which until today
  sat in `rg6_description` (onrobot-rg6). Not one of the three things in that
  file is a gripper part in the sense that package means: the sensor arch and
  the ArUco marker belong to the platform, and the gripper block is the
  MOUNTING of the hand on this robot's arm, which names `arm_0_tool0` — a frame
  that only exists once the Clearpath generator has built an a200 with a UR5.
- **The dependency direction is the point.** A component package that carries
  its integration cannot be reused: `rg6_description` described an RG6 *and*
  where it sits on one particular Husky. It now describes only the hand, and
  this package includes its macro. Nothing points the other way.
- **`robot.yaml` gained a second workspace.** `system.ros2.workspaces` lists
  `/home/robot/husky-extras/install/setup.bash` next to the rg6 one, and
  `platform.extras.urdf.path` points here. Both are needed together: the
  generator finds the file by path but expands `$(find rg6_description)` and
  `package://husky_extras_description` through the ament index the workspaces
  build up.
- **Ten tests, and they guard the seam rather than the geometry.** That the
  file is well-formed XML — an XML comment cannot contain `--`, and that
  mistake took the whole stack down once already; that every `package://` URI
  names a package which actually ships the file; that the four link names other
  repos hold on to survived the move; and that `robot.yaml` in the neighbouring
  repo still addresses this path and lists this workspace.
- **The arch inertia arrived with the file, and it was derived the same day.** `husky_top_assembly` carried six
  collision boxes and no mass at all, so `twinlink.urdf_mujoco._ensure_inertial` was substituting 0.1 kg for a
  half-metre portal frame, a factor of 62. 2.3 L of measured structure volume at the assumed density of 6xxx
  aluminium gives 6.21 kg, distributed over the six boxes by volume with the box mode of `onrobot-rg6`'s
  `tools/derive_link_inertia.py`. The volume is measured, the density is not; R47 carries the scale.
- **The naked `TODO`s at the ArUco marker became R48.** Neither its parent frame
  nor its offset has ever been measured; the marker is visual only, so nothing
  plans against it, but a reader of the viewer and any pose estimation trusting
  the frame are misled. A `TODO` without a number and a date says neither who
  decides it nor what it hangs on.
- **CI, and it runs the suite in a workspace rather than in the repo alone.**
  `.github/workflows/ci.yml` checks this repo out at `robot/husky-extras`,
  `husky-custom-setup` next to it and touches `workspace.repos` between them,
  because the check that reads `robot.yaml` skips by name while there is no
  workspace root above the repo — measured here: nine passed and one skipped
  without the marker, ten passed with it. That skip would have made the
  workflow green having compared nothing, and the far side is exactly the
  change that goes unnoticed otherwise. Plus `ruff check --select
  E9,F63,F7,F82`; no `colcon build`, which would install two directories and
  run no test, and no `ruff format --check`, which without a `pyproject.toml`
  measures against line-length 88 instead of the workspace's 120.
