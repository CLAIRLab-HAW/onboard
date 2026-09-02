"""Topic and frame names of the navigation layer -- the single source.

ROS-free.  The launch files in ../../launch/ import from here; a test holds them to not stating the values a second
time.
"""

from __future__ import annotations

#: Namespace of the a200-0553.  The whole graph hangs off it.
NAMESPACE = "a200_0553"

#: The frame robot.yaml generates for the lidar3d entry and that the driver
#: writes into every PointCloud2.  If the two diverge, tf2 does not find the
#: cloud and does not report it.
LIDAR_FRAME = "lidar3d_0_laser"

#: Root link of the URDF (robot-contract profile: frames.base_link).
BASE_FRAME = "base_link"

#: tf2 broadcasts on the ABSOLUTE names; the node namespace does not take
#: effect there.  Without these remaps a node publishes globally while the
#: rest of the graph listens on /a200_0553/tf -- an empty TF chain without an
#: error.
TF_REMAPS = [("/tf", "tf"), ("/tf_static", "tf_static")]


def points_topic() -> str:
    """Raw point cloud of the RS16 (sensor_msgs/PointCloud2)."""
    return f"/{NAMESPACE}/sensors/lidar3d_0/points"


def scan_topic() -> str:
    """2D scan derived from the cloud (sensor_msgs/LaserScan).

    AMCL and slam_toolbox read LaserScan EXCLUSIVELY -- neither of them can process a PointCloud2.  This node is
    therefore not a convenience but a precondition.
    """
    return f"/{NAMESPACE}/sensors/lidar3d_0/scan"


def cmd_vel_topic() -> str:
    """Nav2's drive command.

    This is the twist_mux input ``external`` (priority 1, the lowest) -- joystick, RC and interactive marker therefore
    override Nav2 at any time.  The type is geometry_msgs/TwistStamped, not Twist.
    """
    return f"/{NAMESPACE}/cmd_vel"


def pointcloud_to_laserscan_params() -> dict:
    """Parameters of the pointcloud_to_laserscan node.

    The height band is RELATIVE TO base_link (target_frame) and has to contain the driving plane -- a band above or
    below it delivers nothing but ``inf`` and looks like a broken driver.
    """
    return {
        "target_frame": BASE_FRAME,
        "transform_tolerance": 0.05,
        # Band around the driving plane: everything between 10 cm below and 50 cm above base_link.  base_link sits
        # 13,228 cm above the ground (the URDF puts base_footprint at z=-0.13228 underneath it), so the band starts
        # just above the ground.
        "min_height": -0.10,
        "max_height": 0.50,
        "angle_min": -3.141592653589793,
        "angle_max": 3.141592653589793,
        "angle_increment": 0.0087,  # 0,5 degrees ─▶ 720 rays
        "scan_time": 0.1,  # the RS16 spins at 10 Hz
        # Below 20 cm the sensor sees its own housing; in the costmap those points would become a ring of obstacles
        # around the robot.
        "range_min": 0.2,
        "range_max": 100.0,
        "use_inf": True,
        "inf_epsilon": 1.0,
    }
