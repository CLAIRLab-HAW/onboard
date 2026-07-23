#!/usr/bin/env python3
"""octomap_feed: gedrosselte Depth->PointCloud2-Quelle fuer MoveIts Octomap.

Onboard-Gegenstueck zu Schritt 2 der HRL-Hindernis-Architektur (dichte
Sicherheitsschicht): move_group bekommt ueber den Occupancy Map Monitor
(``PointCloudOctomapUpdater``, s. clearpath-custom-setup.py Patch-Schritt 5)
eine Punktwolke der Wrist-D435 und pflegt daraus einen probabilistischen
Voxel-Octree -- Raycasts raeumen freigewordenen Raum automatisch, beliebige
Formen werden bei Voxelaufloesung erfasst, und die vom Mac gepushten
Collision-Objects (Wuerfel, Boden-Slab, Hindernis-Boxen) maskiert MoveIt
selbst aus dem Octree (PlanningSceneMonitor exclude*FromOctree).

Warum ein eigener Node statt realsense pointcloud.enable / depth_image_proc:

* Die RealSense laeuft mit 30 fps -- Octomap-Insertion bei 30 Hz frisst den
  Onboard-Rechner.  Hier wird auf ``rate_hz`` (Default 5) gedrosselt und mit
  ``stride`` (Default 2) subsampled: 320x240 Punkte @ 5 Hz sind fuer den
  Updater bequem.
* ``DepthImageOctomapUpdater`` (der Depth direkt konsumieren koennte)
  self-filtert per OpenGL-Offscreen-Rendering -- auf dem headless Onboard-PC
  fragil.  Der ``PointCloudOctomapUpdater`` filtert geometrisch (kein GL),
  braucht aber eine PointCloud2: die liefert dieser Node.
* Kein zusaetzliches apt-Paket, keine Composition: rclpy + numpy (beides da).

Die Wolke wird im OPTISCHEN Frame der Kamera publiziert (frame_id/stamp der
Depth-Message durchgereicht); die TF-Transformation in den ``octomap_frame``
macht der Updater selbst.  QoS: Publisher RELIABLE (matcht sowohl reliable
als auch best-effort Subscriber -- die QoS des MoveIt-Updaters muss uns damit
nicht kuemmern), Subscriber SensorData (best effort, wie die Kamera).

Aufruf (Service clearpath-custom-octomap-feed, s. Installer):
    octomap-feed --ros-args -p depth_topic:=... -p rate_hz:=5.0

Selbsttest ohne ROS (nur numpy -- laeuft auch auf dem Mac):
    python3 octomap_feed.py --selftest
"""
from __future__ import annotations

import sys

import numpy as np

# --------------------------------------------------------------------------- #
# Pure Konvertierung (ROS-frei, damit ohne Roboter testbar)
# --------------------------------------------------------------------------- #


def depth_to_cloud(
    depth: np.ndarray,
    K: np.ndarray,
    stride: int = 2,
    min_depth: float = 0.15,
    max_depth: float = 2.5,
) -> np.ndarray:
    """Depth-Bild -> (N, 3) float32 Punkte im OPTISCHEN Kameraframe.

    ROS-Optik-Konvention (REP 103): x rechts, y unten, z vorwaerts --
    x = (u-cx)/fx * z, y = (v-cy)/fy * z.  ``depth`` in Metern (float) oder
    Millimetern (uint16, wird konvertiert).  Ungueltige/ausserhalb
    [min_depth, max_depth] liegende Pixel fallen weg.
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
    return np.stack(
        [(us - cx) / fx * z, (vs - cy) / fy * z, z], axis=1
    ).astype(np.float32)


def selftest() -> int:
    """Numpy-only Plausibilitaetstest der Konvertierung."""
    h, w = 120, 160
    K = np.array([[140.0, 0.0, w / 2.0], [0.0, 140.0, h / 2.0], [0.0, 0.0, 1.0]])
    depth = np.full((h, w), 1.2, dtype=np.float32)
    depth[40:60, 60:100] = 0.8  # ein "Objekt" naeher an der Kamera
    depth[0:5, :] = 0.0  # ungueltige Zeilen

    pts = depth_to_cloud(depth, K, stride=2, min_depth=0.15, max_depth=2.5)
    assert pts.dtype == np.float32 and pts.shape[1] == 3, "shape/dtype"
    assert len(pts) > 0.9 * (h / 2) * (w / 2) - (5 * w / 4), "zu viele Punkte verworfen"
    assert np.all(pts[:, 2] > 0.15) and np.all(pts[:, 2] < 2.5), "z-Band"
    # Hauptpunkt-Pixel muss auf der optischen Achse landen (x=y=0, z=depth).
    centre = depth_to_cloud(depth, K, stride=1)[
        np.argmin(np.abs(depth_to_cloud(depth, K, stride=1)[:, :2]).sum(axis=1))
    ]
    assert abs(centre[0]) < 1e-3 and abs(centre[1]) < 1e-3, "Hauptpunkt"
    # mm-Eingang (uint16) muss identisch skalieren.
    mm = (depth * 1000.0).astype(np.uint16)
    pts_mm = depth_to_cloud(mm, K, stride=2)
    assert len(pts_mm) == len(pts), "mm/uint16-Pfad"
    assert np.allclose(pts_mm[:, 2], pts[:, 2], atol=1e-3), "mm-Skalierung"
    print("octomap_feed selftest: OK "
          f"({len(pts)} Punkte, z {pts[:, 2].min():.2f}..{pts[:, 2].max():.2f} m)")
    return 0


# --------------------------------------------------------------------------- #
# ROS-Node (nur importiert, wenn nicht --selftest)
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()

    import struct  # noqa: F401  (nur zur Dokumentation: Layout ist 3x float32)

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField

    class OctomapFeed(Node):
        def __init__(self) -> None:
            super().__init__("octomap_feed")
            ns = self.declare_parameter(
                "camera_ns", "/a200_0553/sensors/camera_0"
            ).value
            # Treiber-registriertes aligned-Depth (robot.yaml align_depth.enable):
            # heisst beim realsense2_camera-Treiber '.../image', NICHT
            # '.../image_raw' (Kontrakt-Profil camera.depth).
            self.depth_topic = self.declare_parameter(
                "depth_topic", f"{ns}/aligned_depth_to_color/image"
            ).value
            self.info_topic = self.declare_parameter(
                "info_topic", f"{ns}/aligned_depth_to_color/camera_info"
            ).value
            self.cloud_topic = self.declare_parameter(
                "cloud_topic", f"{ns}/octomap_points"
            ).value
            self.rate_hz = float(self.declare_parameter("rate_hz", 5.0).value)
            self.stride = int(self.declare_parameter("stride", 2).value)
            self.min_depth = float(self.declare_parameter("min_depth", 0.15).value)
            self.max_depth = float(self.declare_parameter("max_depth", 2.5).value)

            self._depth = None  # letzte Depth-Message (Rohdaten)
            self._K = None
            self._published_stamp = None

            self.create_subscription(
                Image, self.depth_topic, self._on_depth, qos_profile_sensor_data
            )
            self.create_subscription(
                CameraInfo, self.info_topic, self._on_info, qos_profile_sensor_data
            )
            # RELIABLE matcht reliable- UND best-effort-Subscriber; KEEP_LAST 2
            # haelt den Speicher klein.
            self._pub = self.create_publisher(
                PointCloud2, self.cloud_topic,
                QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE),
            )
            self.create_timer(1.0 / max(self.rate_hz, 0.1), self._tick)
            self.get_logger().info(
                f"octomap_feed: {self.depth_topic} -> {self.cloud_topic} "
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
                return  # kein neues Bild seit dem letzten Tick
            enc = (msg.encoding or "").lower()
            if enc in ("16uc1", "mono16"):
                depth = np.frombuffer(msg.data, dtype=np.uint16)
            elif enc == "32fc1":
                depth = np.frombuffer(msg.data, dtype=np.float32)
            else:
                self.get_logger().warning(
                    f"unbekanntes Depth-Encoding {msg.encoding!r} -- Frame verworfen",
                    throttle_duration_sec=10.0,
                )
                return
            try:
                depth = depth.reshape(msg.height, msg.width)
            except ValueError:
                return
            pts = depth_to_cloud(
                depth, K, self.stride, self.min_depth, self.max_depth
            )
            cloud = PointCloud2()
            cloud.header = msg.header  # Frame + Stamp der Kamera durchreichen
            cloud.height = 1
            cloud.width = len(pts)
            cloud.fields = [
                PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1)
                for i, n in enumerate("xyz")
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
        pass  # normaler Stopp (Ctrl+C / systemd)
    except Exception:
        # SIGTERM-Shutdown-Race (systemd stop): rclpys Signal-Handler
        # invalidiert den Context, waehrend spin noch ein WaitSet baut ->
        # RCLError "context is not valid".  Das ist ein normaler Stopp --
        # nur bei noch gueltigem Context ist es ein echter Fehler.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
