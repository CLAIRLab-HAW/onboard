"""self_filter: the RS16's points without the robot's own body.

The RS16 on the a200's sensor arch sees the arch beside it and an arm reaching out in front. The arch stands inside the
footprint, which the costmaps clear; the arm does not, and in the costmaps it stood as an obstacle right ahead of the
robot -- "RegulatedPurePursuitController detected collision ahead!" on every drive with the arm out, and a trail of
marks along its way (2026-09-27, ManiSkill stack).  This node drops every point inside one of the robot's collision
hulls (:class:`clair.twin.body.RobotBody`: the live description, the links where TF has them at the cloud's stamp)
and publishes the rest on :func:`~clair.navigation.wiring.filtered_points_topic` -- what the costmaps and
pointcloud_to_laserscan read.  Until the description has come, and without ``clair-twin[body]`` installed, it passes
every point through: an unfiltered scan beats none.

``robot_body_filter`` would do this, and more (shadows), but has no ROS 2 port: its ``ros2`` branch is the catkin
package with one CI commit on top, unreleased for Jazzy (checked 2026-09-27).  Hence this, on the hulls the splat map
already leaves the robot out with.

Invocation (mock.py and lidar.launch.py start it)::

    python3 -m clair.navigation.self_filter --ros-args -p use_sim_time:=true
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("clair.navigation.self_filter")

#: How far from the sensor a point can still be the robot's [m]: the RS16 sits on the rear of the arch, and the arm
#: reaches some 1.6 m ahead of it.  Only the points nearer than this go through the hulls.
NEAR_M = 2.2
#: How far around a link a point still counts as the robot [m]: the RS16's centimeter noise and a link a TF tick off.
PADDING_M = 0.05


def robot_points(xyz: np.ndarray, inside, near_m: float = NEAR_M) -> np.ndarray:
    """Which of the sensor-frame points ``xyz`` (N, 3) are the robot's: nearer than ``near_m`` and ``inside`` it.

    :param inside: ``points (M, 3) -> bool (M,)``, the body's containment test in the same frame.
    """
    mask = np.zeros(len(xyz), bool)
    near = np.flatnonzero(np.einsum("ij,ij->i", xyz, xyz) < near_m * near_m)
    if len(near):
        mask[near] = inside(xyz[near])
    return mask


def _rotation(q) -> np.ndarray:
    x, y, z, w = q.x, q.y, q.z, q.w
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _find_package(name: str) -> Path | None:
    from ament_index_python.packages import PackageNotFoundError, get_package_share_directory

    try:
        return Path(get_package_share_directory(name))
    except PackageNotFoundError:
        return None


def main() -> None:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.experimental import EventsExecutor
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
    from rclpy.time import Time
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from std_msgs.msg import String
    from tf2_ros import Buffer, TransformException, TransformListener

    from clair.navigation import wiring

    try:
        from clair.log import console

        console.setup()
    except ImportError:  # the robot: clair-log is a private repository and is not cloned there (2026-09-29)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from clair.twin.body import RobotBody
    except ImportError as exc:  # a robot without clair-twin[body]: the chain must not lose its scan over it
        RobotBody = None
        log.error("no robot body to filter with (%s) -- the points pass through unfiltered", exc)
    rclpy.init(
        args=[
            "--ros-args",
            "-r",
            f"__ns:=/{wiring.NAMESPACE}",
            "-r",
            f"/tf:=/{wiring.NAMESPACE}/tf",
            "-r",
            f"/tf_static:=/{wiring.NAMESPACE}/tf_static",
            *_ros_args(),
        ]
    )
    node = Node("self_filter")
    tf_buffer = Buffer()
    TransformListener(tf_buffer, node)
    publisher = node.create_publisher(PointCloud2, wiring.filtered_points_topic(), 1)
    state: dict = {"body": None, "urdf": None, "dropped": 0, "seen": 0, "said": time.monotonic()}

    def on_description(msg: String) -> None:
        if RobotBody is not None and msg.data and msg.data != state["urdf"]:
            state["urdf"] = msg.data
            state["body"] = RobotBody(msg.data, _find_package, padding_m=PADDING_M)
            body = state["body"]
            log.info("the robot's body: %d hulls on %d links, dropped from the lidar", len(body.hulls), len(body.links))

    def poses(frame: str, stamp) -> dict:
        found = {}
        for link in state["body"].links:
            try:
                t = tf_buffer.lookup_transform(frame, link, Time.from_msg(stamp)).transform
            except TransformException:
                try:  # the cloud's stamp not in the buffer yet: the latest the arm stood at
                    t = tf_buffer.lookup_transform(frame, link, Time()).transform
                except TransformException:
                    continue
            found[link] = (np.array([t.translation.x, t.translation.y, t.translation.z]), _rotation(t.rotation))
        return found

    def on_points(msg: PointCloud2) -> None:
        body = state["body"]
        if body is None:
            publisher.publish(msg)
            return
        points = point_cloud2.read_points(msg, skip_nans=False)
        xyz = np.column_stack([points["x"], points["y"], points["z"]]).astype(float)
        at = poses(msg.header.frame_id, msg.header.stamp)
        drop = robot_points(xyz, lambda p: body.inside(p, at))
        publisher.publish(point_cloud2.create_cloud(msg.header, msg.fields, points[~drop]))
        state["dropped"] += int(drop.sum())
        state["seen"] += len(xyz)
        if time.monotonic() - state["said"] > 60.0:
            log.info("%d of %d points were the robot's in the last minute", state["dropped"], state["seen"])
            state.update(dropped=0, seen=0, said=time.monotonic())

    latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(String, wiring.description_topic(), on_description, latched)
    node.create_subscription(PointCloud2, wiring.points_topic(), on_points, qos_profile_sensor_data)
    log.info("%s without the robot's body -> %s", wiring.points_topic(), wiring.filtered_points_topic())
    try:
        # The events executor: the TF listener takes every one of the robot's ~90 TF messages a second, and the
        # default executor rebuilt its wait set for each -- half this node's 21 % CPU (py-spy, 2026-09-27).
        rclpy.spin(node, executor=EventsExecutor())
    except (KeyboardInterrupt, ExternalShutdownException):
        pass


def _ros_args() -> list[str]:
    import sys

    return sys.argv[sys.argv.index("--ros-args") + 1 :] if "--ros-args" in sys.argv else []


if __name__ == "__main__":
    raise SystemExit(main())
