"""Read ten depth images off a standing sim camera and print, as JSON, their encoding, how much of the image has
depth, and how far each pixel's depth scatters against its median distance.

Copied into offboard-plant-mock-1 and run there by ``test_sim_base_e2e.py`` (``source ros-env``; TARGET=mock only).
"""

from __future__ import annotations

import json
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

rclpy.init(args=["--ros-args", "-p", "use_sim_time:=true"])
node = Node("sim_depth")
frames: list[Image] = []
node.create_subscription(
    Image, "/a200_0553/sensors/camera_0/aligned_depth_to_color/image", frames.append, qos_profile_sensor_data
)
deadline = time.monotonic() + 40.0
while len(frames) < 12 and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.1)
kept = frames[2:]  # the first two may straddle the switch
depth_m = np.stack([np.frombuffer(f.data, dtype="<u2").reshape(f.height, f.width) for f in kept]) * 0.001
seen = (depth_m > 0).all(axis=0)
print(
    json.dumps(
        {
            "encoding": kept[0].encoding,
            "frames": len(kept),
            "valid_share": float(seen.mean()),
            "median_depth_m": float(np.median(depth_m[:, seen])) if seen.any() else 0.0,
            "median_depth_std_m": float(np.median(depth_m[:, seen].std(axis=0))) if seen.any() else 0.0,
        }
    )
)
