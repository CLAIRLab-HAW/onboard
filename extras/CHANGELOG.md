# Changelog — husky-extras

What changed when. The current state is described in the [README](README.md).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
the versioning [Semantic Versioning](https://semver.org/).


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
- **The naked `TODO`s at the ArUco marker became R48.** Neither its parent frame
  nor its offset has ever been measured; the marker is visual only, so nothing
  plans against it, but a reader of the viewer and any pose estimation trusting
  the frame are misled. A `TODO` without a number and a date says neither who
  decides it nor what it hangs on.
