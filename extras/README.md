# husky-extras

The URDF extras of the **a200-0553**: everything this particular robot has that
neither Clearpath's own description nor a component package knows about — the
sensor arch on the top plate, the ArUco marker, and the mounting of the OnRobot
RG6 on the UR5 flange.

One file does all of it,
`src/husky_extras_description/urdf/clearpath_extras.urdf.xacro`, and the
Clearpath generator pulls it in through `robot.yaml`:

```yaml
platform:
  extras:
    urdf:
      path: /home/robot/husky-extras/src/husky_extras_description/urdf/clearpath_extras.urdf.xacro
```

**Why this is a repo of its own.** Every link here hangs on a frame that only
exists once the generator has built an a200 with a UR5 on it — `arm_0_tool0`,
`top_plate_rear_mount`, `top_plate_front_mount`. A component package must not
know those: `rg6_description` describes an RG6, which is the same hand on any
arm, and it stayed unusable elsewhere for as long as it carried this robot's
assembly. The dependency runs one way only — this package includes the gripper
macro, the gripper package includes nothing from here.

## Features

- **The sensor arch as a body, not a picture** — a glTF `<visual>` plus six
  collision boxes along the real structure (2.3 L of material in a 91.3 L hull;
  a single bounding box would have walled up the whole rear) and an `<inertial>`
  of 6.21 kg. Until 2026-08-20 the link had no collision at all and MoveIt
  planned straight through it (R15); until 2026-08-31 no mass, so both
  simulators carried a half-metre portal frame as 0.1 kg (R47).
- **The RG6 at `arm_0_tool0`**, without a mounting offset (the bracket screws
  onto the flange) and rotated by π, measured on the device rather than guessed.
- **Two frames the rest of the stack addresses by name**:
  `rg6_onrobot_rg6_base_link`, which `robot.yaml` hangs the camera on, and
  `rg6_hand_tcp`, the TCP that every calibrated quantity is expressed against.
- **The ArUco marker**, visual only — and explicitly unsurveyed (R48).

## Tech Stack

- **ROS 2 Jazzy**, `ament_cmake`, xacro — the package builds nothing, it
  installs `urdf/` and `meshes/` so `package://husky_extras_description/…`
  resolves through the ament index.
- **pytest** for the seam checks, ROS-free and robot-free.

## Installation

The robot clones and builds it like the gripper workspace; the installer of
[husky-custom-setup](../husky-custom-setup/README.md) does that, and
`robot.yaml` lists the result under `system.ros2.workspaces`.

```bash
cd ~/husky-extras && colcon build --packages-select husky_extras_description
```

In the offboard container the package comes out of the build context and is
built into `/opt/husky-extras`; the entrypoint symlinks `/home/robot/husky-extras`
onto it so the absolute paths from `robot.yaml` resolve there as well.

## Usage

Nothing here is started. The file is read by

- `clearpath_generator_common generate_description` (per boot, on the robot and
  in the `mock-robot` container),
- RViz and the `foxglove_bridge`, which resolve the arch mesh through the
  ament index of their own container,
- and `tools/derive_link_inertia.py` in `onrobot-rg6`, whose box mode recomputes
  the arch inertia from the six collision boxes:

```bash
python3 ../onrobot-rg6/tools/derive_link_inertia.py --box-link \
    src/husky_extras_description/urdf/clearpath_extras.urdf.xacro husky_top_assembly 6.21
```

## Running Tests

```bash
uv run pytest robot/husky-extras/tests
```

Ten checks, from the workspace root and without ROS: that the file is
well-formed XML (an XML comment cannot contain `--`, and a malformed extras file
takes `move_group` down with it), that every `package://` URI names a package
that really ships the file, that the four addressed link names survived, and
that `robot.yaml` in `husky-custom-setup` still points at this path and lists
this workspace.

## Related

- [onrobot-rg6](../onrobot-rg6/README.md) — the RG6 model whose macro this file
  instantiates, and `rg6_moveit_patch`, which puts the gripper into the
  generated SRDF
- [husky-custom-setup](../husky-custom-setup/README.md) — `robot.yaml` (SSOT),
  the boot patcher and the installer that rolls this workspace out
- [husky-offboard](../../deploy/husky-offboard/README.md) — the container that
  reconstructs the same setup without a robot

## Versioning

[Semantic Versioning](https://semver.org/); what changed when is in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT. The RG6 model this file instantiates is vendored in `onrobot-rg6`; its
origin and the changes made to it are documented there
(`LICENSE-THIRD-PARTY.md`).
