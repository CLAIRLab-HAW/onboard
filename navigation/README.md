# husky-navigation

Provides the mobile-base capability; locomotion remains outside the first manipulation milestone.
See the [physical-intelligence architecture](../../docs/COGNITIVE-ARCHITECTURE.md).

Navigation layer of the Husky **a200-0553**: the sensor path of the RoboSense
RS-LiDAR-16, and Nav2. Runs in the offboard container against the mock
platform **and** onboard on the real robot — same configuration, same driver.

## Features

- **One driver for the real sensor.** `rslidar_sdk` (apt, `ros-jazzy-rslidar-sdk`) reads the device on the robot and
  the recording `data/recordings/rs16_labor.pcap` in the container; the difference is `common.msg_source`. A sim
  plant (ManiSkill, MuJoCo) casts the RS16 in its world instead and publishes on the same topic, so the chain behind
  the points is the same.
- **The robot's own body out of the points.** `self_filter` (`python3 -m clair.navigation.self_filter`) drops the
  RS16's points inside the robot's collision hulls -- the sensor arch beside it, an arm reaching out -- and publishes
  the rest on `…/lidar3d_0/points_filtered`, which the scan and the costmaps read. It needs `clair-twin[body]`;
  without it, the points pass through unfiltered.
- **Nav2** with switchable localization (`localization:=none|slam|amcl`): a static identity `map→odom`,
  `slam_toolbox` while mapping, or AMCL against a stored map.
- **ROS-free core.** The decisions live in `src/clair/navigation/` and are
  testable without ROS; the launch files import them.

## Status

**Nav2 drives in the container, not yet on the robot.** Evidenced, not claimed: on the plain mock a
`NavigateToPose` over 1 m ends with `SUCCEEDED`, and the EKF odometry before and after confirms the distance; on the
ManiSkill stack it reaches goals around the furniture of an ArchitecTHOR scene (see the CHANGELOG). On the robot the
RS16 chain runs as a service of the installer (`lidar.launch.py`, scans at 10.6 Hz), but `nav` has no start path
there and there is no map of the lab yet (R36).

**Localization is wheel odometry everywhere; what corrects it depends on where it runs.** `start_nav` in `clair.stack`
passes `localization:=slam` to a sim plant with the lidar on; everything else gets the launch default `none`.

| Where | `odom→base_link` (EKF input) | `map→odom` | Obstacles in the costmaps |
|---|---|---|---|
| plain mock (`plant:=mock`) | mock wheels | static identity | none, synthetic map |
| sim plant, lidar on (the default) | mock wheels + sim UM7 yaw rate | `slam_toolbox` | the cast RS16 |
| sim plant, `--no-lidar` | mock wheels + sim UM7 yaw rate | static identity | none |
| real robot | wheel encoders (UM7 meant, not wired: R66) | — (Nav2 not started) | — |

**The sim's odometry errs as the robot's does.** The mock wheels (`mock_components/GenericSystem`) turn exactly as
commanded, and the world does not follow the odometry but `base-truth`, which moves the body for the same wheel speeds
with the robot profile's skid steer (`sim.base.true_separation_multiplier`, 1.875 × 1.10 until R37 measures it). So
the diff drive's odometry turns 10 % too far, the slip scatters about that by the profile's sigmas, and SLAM has
something to correct; the RS16's ranges err by 3 cm. `up.sh --sim-errors off` makes the sim plant exact, live.
`imu-sim` publishes the UM7 on `sensors/imu_0/data` from the world's motion, and the container's EKF fuses its yaw
rate. Clearpath's generator leaves the `imu0` topic out whenever `robot.yaml` carries `ekf_node` extras, which ours
do (R66), so the container adds it for the sim plants — **the robot's generated `localization.yaml` lacks it too**
(R66). The ground truth is on `/sim/base_truth` and, with ManiSkill, the world's root on `/sim/base_pose`; neither
reaches Nav2.

## Frames — the robot sits in the floor, and that is not one

In RViz and Foxglove the Husky visibly stands **13.2 cm below** the map's
ground plane. That looks like a broken URDF and is not one:

```
base_link → base_footprint    z = −0.13228     (URDF)
wheel axle → base_link        z = +0.03282     (URDF)
wheel radius                      0.1651       (control.yaml)
                              0.03282 − 0.1651 = −0.13228   ✓ exact
odom      → base_link         z =  0.000       (EKF)
map       → base_footprint    z = −0.132       ← hence
```

So `base_footprint` is defined **correctly** — exactly where the wheels touch
the ground. The offset arises one level up: the EKF runs with
`base_link_frame: base_link` and `two_d_mode: True` and thereby pins
`base_link` to z = 0 of the odometry plane, although in the URDF base_link
sits 13.2 cm above the ground.

That is Clearpath's convention from the generated `localization.yaml`. It is
not settable via `robot.yaml` (which only carries `enable_ekf: true`), and
patching the generated file would be exactly the drift source this workspace
avoids. **For Nav2 it has no consequence** — what counts there is x, y and
yaw.

Two places where it does count after all:

- **Height bands are measured from `base_link`, not from the ground.**
  `pointcloud_to_laserscan` filters with `min_height: -0.10`; that is 3.2 cm
  above the ground, not 10 cm below it. It is written down in
  `clair.navigation.wiring` together with this calculation.
- **A ground plane as a collision object at `map` z = 0 would sit 13.2 cm too
  high** — in the middle of the robot. Anyone adding one for the arm puts it
  on `base_footprint`.

`test_the_ground_frame_matches_the_wheel_geometry` nails down the URDF side:
it checks that `base_footprint` matches the wheel axle **and** the
`wheel_radius` from `control.yaml`. Neither source knows about the other; if
they diverge (when switching to outdoor wheels, say), not only the rendering
is wrong but the odometry too — and nobody reports that. Whether the radius
matches the *real* rotation is something the mock cannot check in principle:
see R37.

## Tech Stack

ROS 2 Jazzy · `rslidar_sdk` · `nav2` · `slam_toolbox` ·
`pointcloud_to_laserscan` · Python 3.11+

## Installation

Part of the clearpath uv workspace (`uv sync` at the root). The repo gets into
the offboard image via `additional_contexts` during `docker compose build`.

## Usage

See `deploy/offboard/scripts/nav` in the container.

## Running Tests

```bash
uv run pytest onboard/navigation          # without ROS, without container
uv run pytest -m e2e_container_nav                      # needs a running container
```

## Related

- [Design spec](../../docs/superpowers/specs/2026-08-22-nav2-rs16-design.md)
- [robot-contract profile](../../robot/contract/src/clair/robot/contract/profiles/a200_0553.yaml)

## Versioning

[SemVer](https://semver.org/), history in the [CHANGELOG](CHANGELOG.md).

## License

See the workspace.
