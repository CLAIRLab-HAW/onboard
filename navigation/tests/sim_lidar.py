"""Read ten sweeps of the RS16 off a standing sim base and print, as JSON, how far each ray's range scatters.

Copied into offboard-plant-mock-1 and run there by ``test_sim_base_e2e.py`` (``source ros-env``; TARGET=mock only).
"""

from __future__ import annotations

import json
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2

rclpy.init(args=["--ros-args", "-p", "use_sim_time:=true"])
node = Node("sim_lidar")
sweeps: list[np.ndarray] = []


def on_points(msg: PointCloud2) -> None:
    sweeps.append(np.linalg.norm(point_cloud2.read_points_numpy(msg, ["x", "y", "z"]), axis=1))


node.create_subscription(PointCloud2, "/a200_0553/sensors/lidar3d_0/points", on_points, 5)
deadline = time.monotonic() + 30.0
while len(sweeps) < 12 and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.1)
kept = sweeps[2:]  # the first two may straddle the switch
width = min(len(s) for s in kept)
ranges_m = np.stack([s[:width] for s in kept])
print(json.dumps({"sweeps": len(kept), "median_range_std_m": float(np.median(ranges_m.std(axis=0)))}))
