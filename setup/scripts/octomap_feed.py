#!/usr/bin/env python3
"""octomap_feed: throttled depth─▶PointCloud2 source for MoveIt's octomap.

Onboard counterpart to step 2 of the HRL obstacle architecture (the dense safety layer): through the occupancy map
monitor (``PointCloudOctomapUpdater``, see clearpath-custom-setup.py patch step 5) move_group receives a point cloud
from the wrist D435 and maintains a probabilistic voxel octree from it -- raycasts clear freed space automatically,
arbitrary shapes are captured at voxel resolution, and MoveIt masks the collision objects pushed by the workstation
(cubes, floor slab, obstacle boxes) out of the octree itself (``PlanningSceneMonitor`` ``exclude*FromOctree``).

Why a dedicated node instead of realsense ``pointcloud.enable`` / ``depth_image_proc``:

* The RealSense runs at 30 fps -- octomap insertion at 30 Hz eats the onboard
  computer.  Here it is throttled to ``rate_hz`` (default 5) and subsampled
  with ``stride`` (default 2): 320x240 points at 5 Hz are comfortable for the
  updater.
* ``DepthImageOctomapUpdater`` (which could consume depth directly)
  self-filters via OpenGL offscreen rendering -- fragile on the headless
  onboard PC.  ``PointCloudOctomapUpdater`` filters geometrically (no GL) but
  needs a PointCloud2: this node delivers it.
* No extra apt package, no composition: rclpy + numpy (both present).

The cloud is published in the OPTICAL frame of the camera (frame_id/stamp of the depth message passed through); the TF
transform into ``octomap_frame`` is done by the updater itself.  QoS: publisher RELIABLE (matches both reliable and
best-effort subscribers -- so the QoS of the MoveIt updater does not concern us), subscriber SensorData (best effort,
like the camera).

Invocation (service clearpath-custom-octomap-feed, see installer)::

    octomap-feed --ros-args -p depth_topic:=... -p rate_hz:=5.0

Selftest without ROS (numpy only -- runs on the workstation too)::

    python3 octomap_feed.py --selftest
"""

from __future__ import annotations

import sys

import numpy as np

# --------------------------------------------------------------------------- #
# Pure conversion (ROS-free, so it is testable without a robot)
# --------------------------------------------------------------------------- #


def depth_to_cloud(
    depth: np.ndarray, K: np.ndarray, stride: int = 2, min_depth: float = 0.15, max_depth: float = 2.5
) -> np.ndarray:
    """Depth image ─▶ (N, 3) float32 points in the OPTICAL camera frame.

    ROS optical convention (REP 103): x right, y down, z forward -- ``x = (u-cx)/fx * z``, ``y = (v-cy)/fy * z``.
    ``depth`` in metres (float) or millimetres (uint16, converted).  Invalid pixels and those outside ``[min_depth,
    max_depth]`` are dropped.
    """
    if depth.dtype == np.uint16:
        depth = depth.astype(np.float32) / 1000.0
    h, w = depth.shape[:2]
    stride = max(1, int(stride))
    vs, us = np.mgrid[0:h:stride, 0:w:stride]
    z = depth[vs, us].astype(np.float32).ravel()
    us = us.ravel().astype(np.float32)
    vs = vs.ravel().astype(np.float32)
    ok = np.isfinite(z) & (z > float(min_depth)) & (z < float(max_depth))
    if not np.any(ok):
        return np.empty((0, 3), dtype=np.float32)
    z, us, vs = z[ok], us[ok], vs[ok]
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    if fx <= 0.0 or fy <= 0.0:
        return np.empty((0, 3), dtype=np.float32)
    return np.stack([(us - cx) / fx * z, (vs - cy) / fy * z, z], axis=1).astype(np.float32)


def selftest() -> int:
    """Numpy-only sanity check of the conversion."""
    h, w = 120, 160
    K = np.array([[140.0, 0.0, w / 2.0], [0.0, 140.0, h / 2.0], [0.0, 0.0, 1.0]])
    depth = np.full((h, w), 1.2, dtype=np.float32)
    depth[40:60, 60:100] = 0.8  # an "object" closer to the camera
    depth[0:5, :] = 0.0  # invalid rows

    pts = depth_to_cloud(depth, K, stride=2, min_depth=0.15, max_depth=2.5)
    assert pts.dtype == np.float32 and pts.shape[1] == 3, "shape/dtype"
    assert len(pts) > 0.9 * (h / 2) * (w / 2) - (5 * w / 4), "too many points dropped"
    assert np.all(pts[:, 2] > 0.15) and np.all(pts[:, 2] < 2.5), "z-Band"
    # The principal point pixel must land on the optical axis (x=y=0, z=depth).
    centre = depth_to_cloud(depth, K, stride=1)[
        np.argmin(np.abs(depth_to_cloud(depth, K, stride=1)[:, :2]).sum(axis=1))
    ]
    assert abs(centre[0]) < 1e-3 and abs(centre[1]) < 1e-3, "principal point"
    # The mm input (uint16) must scale identically.
    mm = (depth * 1000.0).astype(np.uint16)
    pts_mm = depth_to_cloud(mm, K, stride=2)
    assert len(pts_mm) == len(pts), "mm/uint16 path"
    assert np.allclose(pts_mm[:, 2], pts[:, 2], atol=1e-3), "mm scaling"
    print(f"octomap_feed selftest: OK ({len(pts)} points, z {pts[:, 2].min():.2f}..{pts[:, 2].max():.2f} m)")
    return 0


# --------------------------------------------------------------------------- #
# ROS node (only imported when not running --selftest)
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()

    import struct  # noqa: F401  (documentation only: the layout is 3x float32)

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField

    class OctomapFeed(Node):
        def __init__(self) -> None:
            super().__init__("octomap_feed")
            ns = self.declare_parameter("camera_ns", "/a200_0553/sensors/camera_0").value
            # Driver-registered aligned depth (robot.yaml align_depth.enable): in the realsense2_camera driver this is
            # '.../image', NOT '.../image_raw' (contract profile camera.depth).
            self.depth_topic = self.declare_parameter("depth_topic", f"{ns}/aligned_depth_to_color/image").value
            self.info_topic = self.declare_parameter("info_topic", f"{ns}/aligned_depth_to_color/camera_info").value
            self.cloud_topic = self.declare_parameter("cloud_topic", f"{ns}/octomap_points").value
            self.rate_hz = float(self.declare_parameter("rate_hz", 5.0).value)
            self.stride = int(self.declare_parameter("stride", 2).value)
            # Near clip 0.3 m = the D435's own near limit (robot.yaml depth_module.min_distance, hardware around
            # 0.28 m): below it the driver delivers nothing usable anyway, so one number now stands for the near
            # end instead of two.
            #
            # CAUTION, this band is narrower than the wrist self-exclusion that used to sit here (0.35 m): the RG6
            # fingers reach ~0.15-0.25 m in front of the camera and a CARRIED payload hangs < ~0.3 m below the TCP.
            # Measured on the robot 2026-07-29, transport after the grasp was unplannable with those voxels in the
            # octree ("<octomap> vs 'Robot attached'" -- the attached-body masking of the occupancy monitor did not
            # take effect).  Whether 0.3 m still keeps them out has NOT been measured -- R50 is that measurement;
            # raise it back to 0.35 if the grasp regression returns.  Nearby REAL obstacles are covered by the
            # object box layer (workstation side, min_depth 0.15 there).
            self.min_depth = float(self.declare_parameter("min_depth", 0.3).value)
            # Far clip 2.5 m cuts BEFORE the move_group updater (robot.yaml max_range, same value) and before the
            # driver's clip_distance 3.0 -- it is the effective range of the dense layer.
            self.max_depth = float(self.declare_parameter("max_depth", 2.5).value)

            self._depth = None  # last depth message (raw data)
            self._K = None
            self._published_stamp = None

            self.create_subscription(Image, self.depth_topic, self._on_depth, qos_profile_sensor_data)
            self.create_subscription(CameraInfo, self.info_topic, self._on_info, qos_profile_sensor_data)
            # RELIABLE matches reliable AND best-effort subscribers; KEEP_LAST 2 keeps memory small.
            self._pub = self.create_publisher(
                PointCloud2, self.cloud_topic, QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE)
            )
            self.create_timer(1.0 / max(self.rate_hz, 0.1), self._tick)
            self.get_logger().info(
                f"octomap_feed: {self.depth_topic} ─▶ {self.cloud_topic} "
                f"@ {self.rate_hz:.1f} Hz, stride {self.stride}, "
                f"z {self.min_depth:.2f}..{self.max_depth:.2f} m"
            )

        def _on_depth(self, msg: Image) -> None:
            self._depth = msg

        def _on_info(self, msg: CameraInfo) -> None:
            self._K = np.array(msg.k, dtype=np.float64).reshape(3, 3)

        def _tick(self) -> None:
            msg, K = self._depth, self._K
            if msg is None or K is None:
                return
            stamp = (msg.header.stamp.sec, msg.header.stamp.nanosec)
            if stamp == self._published_stamp:
                return  # no new image since the last tick
            enc = (msg.encoding or "").lower()
            if enc in ("16uc1", "mono16"):
                depth = np.frombuffer(msg.data, dtype=np.uint16)
            elif enc == "32fc1":
                depth = np.frombuffer(msg.data, dtype=np.float32)
            else:
                self.get_logger().warning(
                    f"unknown depth encoding {msg.encoding!r} -- frame dropped", throttle_duration_sec=10.0
                )
                return
            try:
                depth = depth.reshape(msg.height, msg.width)
            except ValueError as exc:
                # The branch right above throttles a warning for the sibling case (unknown encoding); this one
                # dropped the frame without a word, so a size mismatch looked like no frames arriving at all.
                self.get_logger().warning(
                    f"depth {msg.height}x{msg.width} does not match the payload -- frame dropped: {exc}",
                    throttle_duration_sec=10.0,
                )
                return
            pts = depth_to_cloud(depth, K, self.stride, self.min_depth, self.max_depth)
            cloud = PointCloud2()
            cloud.header = msg.header  # pass the camera frame + stamp through
            cloud.height = 1
            cloud.width = len(pts)
            cloud.fields = [
                PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1) for i, n in enumerate("xyz")
            ]
            cloud.is_bigendian = False
            cloud.point_step = 12
            cloud.row_step = 12 * len(pts)
            cloud.data = pts.tobytes()
            cloud.is_dense = True
            self._pub.publish(cloud)
            self._published_stamp = stamp

    rclpy.init()
    node = OctomapFeed()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # normal stop (Ctrl+C / systemd)
    except Exception:
        # SIGTERM shutdown race (systemd stop): rclpy's signal handler invalidates the context while spin is still
        # building a wait set ─▶ RCLError "context is not valid".  That is a normal stop -- only with a still-valid
        # context is it a real error.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
