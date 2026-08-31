# Husky

The custom setup of the Clearpath a200-0553: an installer that sets up the boot
services, udev rules, the network and the OnRobot RG6, plus the nodes Clearpath
does not ship itself. `config/robot.yaml` is the single source of truth in all
of this — `/etc/clearpath/robot.yaml` is a symlink to the repo clone.

The repo splits into five, and the boundary is mechanical: `config/` holds the
data this robot runs on (`robot.yaml`, the UR5 kinematics calibration, the RTDE
input recipe), `scripts/` the code the installer deploys — exactly what
`--verify` hashes —, `tools/` what a human runs by hand against the robot
(`wakeup.sh`, `shutdown.sh`, `ur-calibrate.sh`, `rg6_stroke_survey.py`),
`tests/` the pytest suite that runs without a robot, and the installer at the
top level ties them together. If a file is in the `--verify` manifest it
belongs in `scripts/`; if it is not, somebody starts it.

## Features

- **Two overlay workspaces come out of `robot.yaml`** — `onrobot-rg6` (the
  gripper) and `husky-extras` (this robot's URDF extras). The installer clones
  and builds both; `system.ros2.workspaces` is what puts them on
  `AMENT_PREFIX_PATH` for the generator, RViz and the `foxglove_bridge` alike.
- **`config/robot.yaml` is the single source of truth** — `/etc/clearpath/robot.yaml`
  is a symlink to the repo clone, so a `git pull` takes effect within seconds
  instead of only at the next boot. On a robot whose symlink still points at the
  old top-level path, the pull that moved the file leaves it dangling: run the
  installer once, it re-points the symlink and says that it did.
- **8 services + 1 timer**, all with the prefix `clearpath-custom-*`.
- **A watchdog for a late arm power-up** and for a motion link that died while
  ExternalControl kept reporting it was "running".
- **The RG6 gripper service** — `clearpath-custom-rg6-grip-bridge`, unit and
  wrapper. The node itself (`rg6_grip_bridge`, XML-RPC against the OnRobot
  URCap) belongs to [onrobot-rg6](../onrobot-rg6/README.md), where its mock
  counterpart already sat; the installer rolls it out from that workspace as a
  root-owned copy, together with its linkage table.
- **Manipulator diagnostics in Cockpit**: arm mode, control, joints,
  controllers and gripper as `diagnostic_msgs`, with an explicit state
  *out of service* instead of invented numbers.
- **A boot patcher with four steps** — everything `robot.yaml` can express has
  moved there. Two of the four edit what the Clearpath generator writes (mesh
  URIs, the arm `joint_states` bus, the RG6's SRDF); `urdf_physics_patch` edits
  what it reads — the UR joints' zero `<dynamics>`, the wheel joints' missing
  one, `top_plate_link` without an `<inertial>` — and therefore runs first.
- **Both Cockpit packages are deployed and measured** — the diagnostics fork
  and the page *Roboter-Werkzeuge*. `--verify` hashes the second one file by
  file, so a page that looks installed but is three commits old says so.

## Tech Stack

Ubuntu + ROS 2 Jazzy on the Clearpath a200-0553, systemd, `rclpy`,
`ur_robot_driver`, Zenoh (`rmw_zenoh_cpp`). A bash installer, no configuration
management.

## Installation

After installing the Clearpath software stack
([Clearpath installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot))
in your own user directory:

```bash
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh
bash -e install-clearpath-custom-setup.sh
```

The installer is interactive and asks before every optional part (`[y/N]`, or
`-y` to say yes to everything). `--verify` checks read-only whether the
deployed copies still match the checkout, and changes nothing. It installs no
package: it writes files and systemd units.

### UR kinematics calibration — separate, on purpose

The individual factory calibration of the UR5 (DH offsets) is **not** part of
the installer. Without it the model computes with nominal values and the real
TCP is off by up to ~1 cm.

```bash
bash tools/ur-calibrate.sh                  # arm powered and reachable
bash tools/ur-calibrate.sh --skip-apt       # the UR stack already matches
```

It stands apart because it does two things an installer should not do without
being asked for them by name: it `apt-get install`s the whole UR stack (the
`ur_calibration` ABI has to match the `ur_client_library`, so they can only be
installed together) on a robot whose UR stack is deliberately pinned, and it
needs a powered arm. Inside the installer, `-y` answered that apt question
without anyone seeing it. Run it in a maintenance window and test the
manipulator afterwards.

Afterwards enter the path it prints in `robot.yaml` at the arm
(`kinematics_parameters_file`) and regenerate — `robot.yaml` is hand
maintained, the script does not touch it.

All units the installer creates carry the prefix `clearpath-custom-*`
(`clearpath-custom-rg6-grip-bridge`, `clearpath-custom-joint-states`,
`clearpath-custom-ur-dashboard`, `clearpath-custom-ur-state-manager`,
`clearpath-custom-manipulator-diagnostics`, `clearpath-custom-octomap-feed`,
`clearpath-custom-manipulators-watchdog.service`/`.timer` and
`clearpath-custom-setup`). The arm controllers are not a service of their own
but part of `ur_state_manager.launch.py` (argument `load_arm_controllers`).
Drop-ins on Clearpath's own units
(`clearpath-manipulators.service.d/override.conf`) keep the name of their
target unit, by systemd convention.

## Usage

What the installed units do, one section each.

### `clearpath-custom-manipulators-watchdog.timer` (late power-up)

The watchdog covers two cases that cannot be fixed from within a ROS node —
both need the dead driver connection for their own inputs and cannot restart
the driver process they depend on. The installer therefore offers a small
**systemd timer** (`scripts/manipulators_watchdog.sh`, a root-owned copy under
`/usr/local/bin/manipulators-watchdog.sh`):

**(a) Arm powered up late.** If the UR5 is powered **long after** the ROS stack
boots, the one-off ros2_control hardware activation of the `ur_robot_driver`
has already failed against the then-unpowered arm — and ros2_control does
**not** repeat it. The driver is left with a dead hardware component, and the
panel stays on **"Stopped"**.

**(b) A hanging reconnect after a `clearpath-robot.service` restart with the
arm already powered.** The old `ExternalControl` instance holds the reverse
socket; the new driver's hardware activation fails on the socket collision →
`joint_state_broadcaster` stays inactive → RViz and MoveIt fall back to the
URDF default pose and the arm lies **flat**.

The health signal is **the `joint_state_broadcaster` stream**
(`/a200_0553/manipulators/joint_states`): it publishes real arm joints **only**
when the ros2_control hardware interface is activated.
`robot_program_running` alone is **not** a valid health signal — that is the
controller-side ExternalControl status (read via dashboard/RTDE) and stays
`true` even when the PC-side motion link is dead. That is exactly case (b).

Every 10 s (from `OnBootSec=90`) it checks: **arm pingable**
(`192.168.131.40`), **but JSC stream silent** → if the arm is **not**
`POWER_OFF`, `systemctl restart clearpath-manipulators.service` runs **once**
(with a cooldown, state in `/run`, so it cannot loop) and after that a restart
of `ExternalControl` (`resend_robot_program`). It does **not** power the arm
(no `power_on`/`brake_release`) — powering up is an operator decision, and this
protects maintenance and end of day; if the arm is on `POWER_OFF` no recovery
runs, so that no driver restart loops against an unpowered arm.
As soon as the operator powers up, the watchdog connects the motion link on the
next tick. Protective and safety stops (`safety_mode != NORMAL`) are **not**
cleared automatically — the `resend` is skipped and releasing stays manual.

A generous grace window (`JS_TIMEOUT`, 25 s) prevents false alarms during the
roughly 15 s the JSC needs after a restart; on a healthy boot (JSC streaming)
and with the arm switched off (not pingable) the watchdog stays silent. The
**gripper** is untouched by this: it hangs off the OnRobot URCap, and no ROS
service can power its tool connector — see the gripper section further down.
Logs: `journalctl -t manipulators-watchdog -b`; schedule:
`systemctl list-timers clearpath-custom-manipulators-watchdog.timer`.

### `clearpath-manipulators.service.d/override.conf` (clean stop)

A drop-in that makes `clearpath-manipulators.service` stop with
`KillSignal=SIGINT` instead of the default `SIGTERM`. `ros2_control_node`,
`move_group` and `robot_state_pub` are ROS nodes and treat `SIGINT` as a
graceful shutdown (reverse and dashboard sockets closed within about 1–3 s);
under `SIGTERM` the old `ros2_control_node` ignores the signal and hangs around
as a zombie for up to 90 s, still holding the reverse socket — which is exactly
what causes the socket collision in case (b) above. The drop-in layers over
Clearpath's own unit and survives package updates.

### `clearpath-custom-manipulator-diagnostics.service` (UR5 + RG6 in Cockpit)

Through the extension
[`cockpit-ros2-diagnostics`](https://github.com/clearpathrobotics/cockpit-ros2-diagnostics),
Cockpit shows the content of `<ns>/diagnostics_agg`. **The manipulator is
missing there entirely** — and in three places at once:

* `clearpath_generator_common` creates analyzers only for platform (power,
  e-stop, drive) and sensors; arm and gripper do not appear in the generator at
  all.
* The arm's `controller_manager` publishes its diagnostics into the
  *manipulators* namespace (`/a200_0553/manipulators/diagnostics`) — not on
  `/a200_0553/diagnostics`, which is what the aggregator subscribes to.
* `ur_robot_driver` delivers its state as `ur_dashboard_msgs`, the gripper as
  flat JSON on `rg6/bridge_state` — neither of them as `diagnostic_msgs`.

Three building blocks close the gap, all from the installer (optional steps):

1. **`manipulator-diagnostics`** (`scripts/manipulator_diagnostics.py`, a
   root-owned copy under `/usr/local/bin`): publishes five statuses at 1 Hz on
   `/a200_0553/diagnostics`. The wrapper needs no `onrobot-rg6` overlay — the
   gripper state arrives as JSON, not as an `rg6_msgs` type:

   | Status | Content |
   |---|---|
   | `Arm Mode` | `robot_mode` + `safety_mode` (latched topics of the `io_and_status_controller`) |
   | `Arm Control` | **the dependable health indicator**: is the joint\_state stream running? |
   | `Arm Joints` | joint angles (rad + °), velocity, effort, rate |
   | `Arm Controllers` | `controller_manager/list_controllers` — which command controller is active |
   | `Gripper` | RG6: width (m/mm/%), force signal, `grip_detected`, `busy`, tool power, last command |

   `Arm Control` deliberately judges the **joint\_state stream**, not
   `robot_program_running`: the latter stays `true` while the PC-side motion
   link is dead — exactly case (b) of the watchdog above. Self-test without
   ROS: `python3 /usr/local/bin/manipulator-diagnostics --selftest`.

   **The arm state decides about the gripper.** The RG6 hangs off the UR tool
   connector — without a powered arm it cannot have any supply at all. The
   state `rg6_grip_bridge` reports on `rg6/bridge_state` is *not* suitable as
   evidence for that: the bridge asks the XML-RPC endpoint in the control box,
   and that answers even when nothing is present at the tool connector — it
   knows what it last commanded, not what the hardware is doing.

   What counts is therefore still the **tool voltage**: an analog signal below
   `dead_input_threshold` (0.2 V) = no valid tool signal. Measured on the
   a200-0553: powered AI2 10.00 V / AI3 1.33 V, unpowered both ~0.056 V. As a
   *width source* AI2 is unusable (miscalibrated by up to 17 mm) — the question
   it answers is solely "is there supply at the tool connector". If the signal
   is invalid, the status reports, depending on the cause,

   | Situation | Message |
   |---|---|
   | arm `POWER_OFF` | **out of service** (grey): `arm switched off - gripper without supply` |
   | arm powered, no signal | **WARNING**: `tool unpowered: is the URCap program running on the pendant?` |
   | arm otherwise unpowered (e.g. `BOOTING`) | **WARNING**: `arm not powered` |

   and width/percent/`grip_detected`/`busy` then read `unknown` instead of
   invented numbers; the raw voltages stay visible (they *are* the diagnosis).

   The same logic applies to the arm itself: `POWER_OFF` is an operator
   decision (maintenance/end of day), not a fault — `Arm Mode`, `Arm Control`,
   `Arm Joints` and the good case of `Arm Controllers` then report **out of
   service** instead of yellow/red. The watchdog behaves the same way (no
   recovery runs at `POWER_OFF`). A real problem still comes through: a safety
   stop stays RED even on a switched-off arm (verified live on a `FAULT` after
   a power cycle), and so does a missing controller. On an unpowered arm the
   joint velocity noise reaches 0.055 rad/s (powered: exactly 0.0000) — which
   is why `moving` reads `unknown` while the arm is off, and the threshold sits
   at 0.02 rad/s (`motion_eps_rad_s`).

   **How "out of service" is encoded:** `diagnostic_msgs` only knows
   OK/WARN/ERROR/STALE. A custom byte value would confuse the aggregator's
   `max()` rollups and every third-party consumer (`rqt_robot_monitor`,
   capture). The status therefore stays **OK** (nothing is broken, after all)
   and additionally carries the value `display=inactive`; only Cockpit turns
   that grey.

2. **`robot.yaml`** under `platform.extras.ros_parameters.diagnostic_aggregator`:
   an AnalyzerGroup `Manipulator` with the subgroups `Arm` and `Gripper`. The
   Clearpath generator merges them into the generated
   `/etc/clearpath/platform/config/diagnostic_aggregator.yaml` and flattens the
   nesting itself into the dotted keys ROS expects; the 20 upstream
   `platform.analyzers.*` and the sensor analyzers stay untouched. The
   analyzers list their statuses as `expected`: if the node dies, they remain
   in the display as **STALE** instead of vanishing without a trace.

   The block sits unconditionally in `robot.yaml`, coupled to no unit file.
   Without the diagnostics node Cockpit therefore shows the group as STALE
   rather than letting it disappear. To remove it = delete the block from
   `robot.yaml`.

3. **Cockpit plugin fork**
   ([`CLAIRLab-HAW/cockpit-ros2-diagnostics`](https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics),
   locally `robot/cockpit-ros2-diagnostics`): in addition to the generic tree, a
   **manipulator panel** (arm card with mode/safety/ExternalControl/motion-link
   badges, joint table and controller chips; gripper card with an opening bar,
   `grip_detected`, tool power, last command). The panel reads the same
   `diagnostics_agg` stream the extension subscribes to anyway — no extra topic
   subscription, so pause, history and reconnect apply unchanged. Without a
   manipulator status in the tree it renders **nothing at all** (robots without
   an arm stay unchanged).

   The fork is also **translated into German** (`po/de.po`; Cockpit loads
   `po.<lang>.js` according to the language setting, the menu entry included)
   and downgrades two third-party messages that used to colour the whole robot
   permanently red: `joy_node: Joystick Driver Status` "Joystick not open." →
   **inactive** (no gamepad plugged in is the normal state) and
   `controller_manager: Hardware Components Activity` "High execution jitter"
   → **warning** (inherent to the base's serial 10 Hz connection). The rules
   live in `src/utils/severity.ts`, apply only on a matching name **and** a
   matching message, and the detail panel still shows the originally reported
   level along with the reason. For the jitter, the cleaner route would be
   `diagnostics.threshold.hardware_components.*` on the `controller_manager` —
   but that switches the message off entirely instead of downgrading it.

   Installation goes to `/usr/local/share/cockpit/ros2-diagnostics`. Cockpit
   searches in the order `~/.local/share/cockpit`, `/etc/cockpit`,
   `/usr/local/share/cockpit`, `/usr/share/cockpit` — so the fork **shadows**
   the apt package without replacing it. To remove it: delete the directory and
   the original is immediately active again (no apt needed). Conversely: as
   long as the fork is in place, apt updates of `cockpit-ros2-diagnostics` are
   not visible — bring the fork up to date when needed.

   **The installer installs no nodejs.** It takes a prebuilt `dist/` from the
   checkout; if that is missing and `npm`+`make` are available, it builds on the
   robot, otherwise it aborts this step with instructions. The recommended
   route (the robot stays toolchain-free):

   ```bash
   git clone https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics.git
   cd cockpit-ros2-diagnostics && make
   rsync -a dist/ robot@<robot>:~/cockpit-ros2-diagnostics/dist/
   ```

**Verification after install + reboot (checklist):**

1. `journalctl -u clearpath-custom-manipulator-diagnostics -b` → start line with
   namespace/topic/rate.
2. `grep -A2 "manipulator.type" /etc/clearpath/platform/config/diagnostic_aggregator.yaml`
   → `diagnostic_aggregator/AnalyzerGroup` (the generator has taken over the
   robot.yaml block; the patcher's journal says nothing about it any more).
3. `ros2 topic echo /a200_0553/diagnostics_agg --once` → entries under
   `/Clearpath Diagnostics/Manipulator/Arm/…` and `…/Gripper`.
4. Cockpit (`http://<robot>:9090` → ROS 2 Diagnostics): card **Manipulator**
   with an arm and a gripper tile.
5. Functional check: open/close the gripper → bar + `grip_detected` follow.
6. Power-off check (`ur_state_manager/power_off`): manipulator tile, arm and
   gripper tile turn **grey/"Außer Betrieb"**, the opening bar disappears,
   `grip_detected`/`busy`/`moving` read `unknown`. Then `prepare` and start the
   URCap program on the panel → everything green again.
   (The tool supply is set by the OnRobot URCap, not by ROS: the route there
   went via tool DO, and the URCap occupies that itself. No ROS service can
   repair this here; until then the status reports WARNING with exactly that
   hint.)
7. Removal check: `systemctl disable --now
   clearpath-custom-manipulator-diagnostics` → the analyzers **stay** in the
   generated YAML and the group shows as **STALE** in `diagnostics_agg`; the
   panel then renders nothing. If the analyzers should go too, remove the block
   from `robot.yaml` (takes effect immediately via `clearpath-robot-check`).

### The two Cockpit packages (no unit of their own)

Both live under `/usr/local/share/cockpit`, which Cockpit searches before
`/usr/share` — and both are optional steps of the installer, not services.

- The [`cockpit-ros2-diagnostics`](../cockpit-ros2-diagnostics/README.md) fork
  goes to `ros2-diagnostics/` and adds the manipulator panel to the diagnostics
  tree. It **shadows** the apt plugin under `/usr/share`, which is why the
  directory name has to be exactly that one.
- [`cockpit-robot-tools`](../cockpit-robot-tools/README.md) goes to
  `robot-tools/` and is the page *Roboter-Werkzeuge*: the offboard-lite
  container plus the VNC address. It shadows **nothing** — no apt package
  carries that name, so it is simply a menu entry of its own.

The second one is the cheaper of the two: static files, no `npm`, no `make`, no
`dist/`, so it never asks for a toolchain on the robot. The installer does not
copy it itself either — it runs the page's own `install.sh`, which is where the
list of files belonging to the package lives. `--verify` reads that same list
and hashes the deployed directory file by file:

```
  DEVIATION        /usr/local/share/cockpit/robot-tools    ◀─ /home/robot/cockpit-robot-tools
                   └─ index.js status.js
```

That comparison exists because the failure it catches has happened: the
deployed page carried an `index.js` three commits behind the checkout and
nothing said so. A `--verify` run needs no root.

### `clearpath-custom-octomap-feed.service` (MoveIt octomap: dense obstacle layer)

Step 2 of the HRL obstacle architecture (step 1 = object-based boxes from the
offboard client via `/twin/scene_update`): through its **occupancy map monitor**
(`PointCloudOctomapUpdater`), `move_group` maintains a probabilistic voxel
octree from the wrist D435 and thereby also avoids obstacles the object tracker
does not know (or does not know yet). Raycasts clear space that has become free
automatically — "freshness" is thus sensor-paced rather than heuristic.

Two building blocks, both from the installer (optional step):

1. **`octomap-feed`** (`scripts/octomap_feed.py`, a root-owned copy under
   `/usr/local/bin`): throttles the camera's 30 fps depth to ~5 Hz, subsamples
   it (stride 2) and publishes `…/sensors/camera_0/octomap_points`
   (PointCloud2 in the optical frame; QoS RELIABLE, matches any subscriber).
   Self-test without ROS: `python3 /usr/local/bin/octomap-feed --selftest`.
2. **Sensor parameters in `robot.yaml`**: under
   `manipulators.moveit.ros_parameters.move_group` sit `octomap_frame`,
   `octomap_resolution`, `sensors` and the `wrist_depth_camera` block — the
   Clearpath generator writes them into
   `/etc/clearpath/manipulators/config/moveit.yaml` itself. `octomap_frame` is
   deliberately `base_link` (odom is UTM-backed on this robot and jumps),
   `octomap_resolution` 0.025, `max_range` 2.0.
   **Careful:** there is no gate "only if `moveit_ros_perception` is
   installed". If the package is missing, `move_group` acknowledges that with a
   plugin load error per boot. On a200-0553 it is installed.

**Interaction with the object collision objects:** MoveIt's PlanningSceneMonitor
masks known world objects and attached bodies out of the octree
(`excludeWorldObjectsFromOctree` / `excludeAttachedBodiesFromOctree`) — so the
cubes pushed from the workstation, the floor slab and the obstacle boxes create
no blocking voxels; grasps stay plannable. The robot itself is geometrically
self-filtered by the updater (`padding_offset` 0.03).

**Prerequisite (deliberately NOT handled by the installer):** the
`PointCloudOctomapUpdater` comes from **`ros-jazzy-moveit-ros-perception`**.
Because the sensor parameters sit in `robot.yaml`, there is no boot-patcher
gate: `move_group` **always** loads the sensor blocks from the generated
`moveit.yaml`, and if the package is missing it acknowledges that with a plugin
load error per boot (see above). Installing it is an **admin decision for a
maintenance window** (apt has taken this robot apart once already — see the
snapshot/hold history): simulate it first with
`apt-get install -s ros-jazzy-moveit-ros-perception` and only proceed if
**nothing** is updated or removed in the process (the candidate
`2.12.4-1noble.20260412.063337` comes from the same snapshot as the installed
`moveit-core` — so the simulation should show only the new package).

**Verification after install + reboot (checklist):**

1. `journalctl -u clearpath-custom-octomap-feed -b` → start line with
   topic/rate.
2. `ros2 topic hz /a200_0553/sensors/camera_0/octomap_points` → ~5 Hz.
3. `grep -A10 wrist_depth_camera /etc/clearpath/manipulators/config/moveit.yaml`
   → the sensor block is in the generated file (it comes from robot.yaml).
4. move_group log: the line "Listening to '…/octomap_points' using message
   filter with target frame 'base_link'" (monitor active).
5. RViz (offboard-lite): PlanningScene display → octomap voxels visible; hold a
   hand in front of the camera → voxels appear, take it away → they disappear
   (raycast).
6. Grasp regression: cube collision objects must carry NO voxels (masking); a
   descent onto a cube must still plan.
7. CPU: `top` on the onboard PC — feed + move_group insertion together should
   stay in the single-digit percent range; otherwise lower `rate_hz`/`stride`
   (ROS params of the unit) and reduce `max_range`.

**Rollback:** `sudo systemctl disable --now clearpath-custom-octomap-feed`
**and** remove the `move_group` block from `robot.yaml` (otherwise the updater
keeps looking for a cloud nobody publishes). The change to robot.yaml takes
effect immediately — `clearpath-robot-check` restarts the stack; the generated
file is recreated on every boot anyway, and a `.bak` sits next to it.

## Running Tests

Three of the Python scripts carry a ROS-free self-test:

```bash
python3 scripts/clearpath_custom_setup.py --selftest
python3 scripts/manipulator_diagnostics.py --selftest
python3 scripts/octomap_feed.py --selftest
```

The fourth, `rg6_grip_bridge --selftest`, moved with the node into
[onrobot-rg6](../onrobot-rg6/README.md) and runs there; the installer still
executes it against the copy it has just deployed.

`urdf_physics_patch` has a dry run instead — it reports every target that is
still waiting for a measurement and writes nothing:

```bash
python3 scripts/urdf_physics_patch --dry-run
```

Its own suite runs from the workspace root, without a robot and without ROS:

```bash
uv run pytest robot/husky-custom-setup/tests
```

The installer runs the same self-test resp. dry run before deploying a file,
and discards a source that does not even compile.
`bash install-clearpath-custom-setup.sh --verify` compares the deployed copies
with the checkout, read-only.

## Related

- [onrobot-rg6](../onrobot-rg6/README.md) — gripper model, MoveIt patch, and
  the gripper on both stages (`rg6_grip_bridge`, `rg6_control_sim`); one of the
  two workspaces `robot.yaml` lists, and the source of three files this
  installer deploys
- [husky-extras](../husky-extras/README.md) — the a200-0553's URDF extras
  (sensor arch, ArUco marker, RG6 mounting), the other one; `robot.yaml`
  addresses its file under `platform.extras.urdf`
- [ur-state-manager](../ur-state-manager/README.md) — arm state and controller
  modes
- [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md) — the panel
  that displays these diagnostics
- [cockpit-robot-tools](../cockpit-robot-tools/README.md) — the Cockpit page
  *Roboter-Werkzeuge*, deployed by the same installer

## Versioning

[Semantic Versioning](https://semver.org/) via the file `VERSION` and
[CHANGELOG.md](CHANGELOG.md).

## License

See the workspace root.
