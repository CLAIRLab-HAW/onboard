# husky-navigation

Navigation layer of the Husky **a200-0553**: the sensor path of the RoboSense
RS-LiDAR-16, and Nav2. Runs in the husky-offboard container against the mock
platform **and** onboard on the real robot — same configuration, same driver.

## Features

- **One driver for both sides.** `rslidar_sdk` (apt, `ros-jazzy-rslidar-sdk`)
  reads a PCAP recording in the mock and the device on the robot. The
  difference: `common.msg_source`.
- **Nav2** with switchable localization: `slam_toolbox` for mapping, AMCL for
  driving against a stored map.
- **ROS-free core.** The decisions live in `src/husky_navigation/` and are
  testable without ROS; the launch files import them.

## Status

**Nav2 drives in the container mock against a synthetic map.** Evidenced, not
claimed: a `NavigateToPose` over 1 m ends with `SUCCEEDED`, and the EKF
odometry before and after confirms the distance.

**The sensor path is built and configured, but never driven.** What is
missing is the RS16 recording (an R item in `ROBOTER-TODO.md`); the
corresponding tests skip themselves with a named cause. Until then:

- `map→odom` comes from a `static_transform_publisher` (identity), not from
  AMCL. An AMCL without scans publishes *no* transform at all.
- Localization rests on wheel odometry alone — the robot drifts against the
  map.
- The costmap has **no** obstacles.

So the sentence is not "Nav2 runs", but: *Nav2 drives in the mock against a
map; the sensor chain is waiting for a recording.*

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
  `husky_navigation.wiring` together with this calculation.
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

See `deploy/husky-offboard/scripts/nav` in the container.

## Running Tests

```bash
uv run pytest onboard/husky-navigation          # without ROS, without container
uv run pytest -m nav_e2e                      # needs a running container
```

## Related

- [Design spec](../../docs/superpowers/specs/2026-08-22-nav2-rs16-design.md)
- [robot-contract profile](../../contract/robot-contract/src/robot_contract/profiles/a200_0553.yaml)

## Versioning

[SemVer](https://semver.org/), history in the [CHANGELOG](CHANGELOG.md).

## License

See the workspace.
