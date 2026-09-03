# onboard — what runs ON the robot

Seven packages that were seven repositories until 2026-09-03. What they have in common is the machine: all of
them are installed on the a200-0553 itself and run there, whether or not a workstation is switched on. That is
the only reason they sit together — they share a deployment target, not a dependency.

| Directory | Was | What it is |
|---|---|---|
| [`setup/`](setup/README.md) | `husky-custom-setup` | The installer, the per-boot patcher, the boot services, the UR5 calibration — and **`robot.yaml`, the single source of truth** every other layer reads. |
| [`extras/`](extras/README.md) | `husky-extras` | This robot's URDF extras: sensor arch, ArUco marker, RG6 on the UR5 flange. One xacro, pulled in by the Clearpath generator through `robot.yaml`. |
| [`rg6/`](rg6/README.md) | `onrobot-rg6` | The RG6 gripper: the measured `rg6_v2` description, the MoveIt patch, the `joint_states` plumbing and the container mock. The real gripper is driven by this package's `rg6_grip_bridge` over the URCap's XML-RPC. |
| [`ur-state/`](ur-state/README.md) | `ur-state-manager` | Arm state (`prepare`, `recover`, `power_off`) and the controller-mode manager. |
| [`navigation/`](navigation/README.md) | `husky-navigation` | The RS-LiDAR-16 sensor path and Nav2 — the same configuration in the container mock and on the robot. |
| [`cockpit-diagnostics/`](cockpit-diagnostics/README.md) | `cockpit-ros2-diagnostics` | A Cockpit plugin: the robot's ROS 2 diagnostics as a web panel. |
| [`cockpit-tools/`](cockpit-tools/README.md) | `cockpit-robot-tools` | A Cockpit page for the recurring manual tasks — today one card: start and stop the offboard `lite` container, with its VNC address. |

**The robot does not know about this directory.** On the machine the checkouts sit directly under
`/home/robot/` — `/home/robot/husky-extras`, `/home/robot/onrobot-rg6` — which is the robot user's home and has
nothing to do with this layer. What the consolidation changes for the robot is filed as **R57** in
[ROBOTER-TODO.md](../ROBOTER-TODO.md); until that is carried out, nothing here reaches it.

## Running tests

```bash
uv run pytest onboard                     # what runs without ROS
uv run pytest -m e2e_container_nav onboard/navigation   # needs a driving base and Nav2
```

`e2e_container_nav` is deselected by the root run. Inside `navigation/` a file lock (`tests/conftest.py`,
`exclusive_base`) serializes the driving tests — without it two xdist workers measure each other's drive.

## Versioning

Each package keeps its own `CHANGELOG.md` and its own version; this directory's
[CHANGELOG.md](CHANGELOG.md) records what happens to the repository as a whole.
