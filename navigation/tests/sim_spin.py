"""Spin a sim plant's base on the spot and compare how far wheel odometry, EKF and ground truth say it turned; first
hold still and read the sim UM7's z axis.  Prints JSON.

Copied into offboard-plant-mock-1 and run there by ``test_sim_base_e2e.py`` (``source ros-env``; TARGET=mock only)::

    python3 sim_spin.py [turns]
"""

from __future__ import annotations

import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu

NS = "/a200_0553"
TOPICS = {
    "wheels": f"{NS}/platform/odom",
    "ekf": f"{NS}/platform/odom/filtered",
    "truth": "/sim/base_truth",
}
OMEGA_RAD_S = 0.5
TURNS = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0


def yaw_of(msg):
    q = msg.pose.pose.orientation
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


rclpy.init(args=["--ros-args", "-p", "use_sim_time:=true"])
node = Node("spin_check")
total = {k: 0.0 for k in TOPICS}
last = {k: None for k in TOPICS}
imu = []


def track(key):
    def cb(msg):
        y = yaw_of(msg)
        if last[key] is not None:
            total[key] += math.remainder(y - last[key], math.tau)
        last[key] = y

    return cb


for k, t in TOPICS.items():
    node.create_subscription(Odometry, t, track(k), 50)
node.create_subscription(Imu, f"{NS}/sensors/imu_0/data", lambda m: imu.append(m.angular_velocity.z), 50)
pub = node.create_publisher(TwistStamped, f"{NS}/cmd_vel", 10)


def spin_for(seconds_wall, omega):
    end = time.monotonic() + seconds_wall
    while time.monotonic() < end:
        msg = TwistStamped()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.twist.angular.z = omega
        pub.publish(msg)
        rclpy.spin_once(node, timeout_sec=0.05)


spin_for(3.0, 0.0)  # settle, collect first samples
missing = [k for k, v in last.items() if v is None]
if missing:
    print(json.dumps({"error": f"no messages on {missing}"}))
    sys.exit(1)
for k in total:
    total[k] = 0.0
imu.clear()
spin_for(5.0, 0.0)
still = list(imu)
for k in total:
    total[k] = 0.0
# Spin until the WHEELS say TURNS turns (the commanded side); the others are compared against that.
deadline = time.monotonic() + 180.0
while abs(total["wheels"]) < TURNS * math.tau and time.monotonic() < deadline:
    spin_for(0.2, OMEGA_RAD_S)
spin_for(3.0, 0.0)
n = len(still)
mean = sum(still) / n if n else float("nan")
std = math.sqrt(sum((v - mean) ** 2 for v in still) / n) if n else float("nan")
print(
    json.dumps(
        {
            "turned_rad": total,
            "wheels_over_truth": total["wheels"] / total["truth"],
            "ekf_over_truth": total["ekf"] / total["truth"],
            "imu_still": {"n": n, "mean_z_rad_s": mean, "std_z_rad_s": std},
        },
        indent=1,
    )
)
node.destroy_node()
rclpy.shutdown()
