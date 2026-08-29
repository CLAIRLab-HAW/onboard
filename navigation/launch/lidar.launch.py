"""Sensor path of the RS16: driver + derivation of the 2D scan.

READ-ONLY.  This launch commands nothing and may therefore also run on the graph of the real robot -- what is barred is
navigation.launch.py, because its controller_server writes to cmd_vel.

Invocation inside the container:
    ros2 launch /opt/spact/husky-navigation/launch/lidar.launch.py \
        pcap:=/data/recordings/rs16_labor.pcap     # mock
    ros2 launch /opt/spact/husky-navigation/launch/lidar.launch.py
                                                   # device (no pcap arg)

Every name comes from husky_navigation.wiring -- none of them is stated a second time here
(tests/test_launch_files_do_not_restate_the_wiring.py).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from husky_navigation import rslidar_config, wiring


def _setup(context, *args, **kwargs):
    pcap = LaunchConfiguration("pcap").perform(context)
    # rslidar_sdk knows no way to override individual keys -- it reads exactly one file.  The resolved version is
    # therefore produced here, from the SAME template the robot uses as well.
    resolved = rslidar_config.write_resolved("/tmp/rslidar_rs16_resolved.yaml", pcap_path=pcap or None)

    return [
        Node(
            package="rslidar_sdk",
            executable="rslidar_sdk_node",
            name="rslidar_sdk_node",
            namespace=wiring.NAMESPACE,
            parameters=[{"config_path": str(resolved)}],
            remappings=wiring.TF_REMAPS,
            output="screen",
        ),
        Node(
            package="pointcloud_to_laserscan",
            executable="pointcloud_to_laserscan_node",
            name="pointcloud_to_laserscan",
            namespace=wiring.NAMESPACE,
            parameters=[wiring.pointcloud_to_laserscan_params()],
            remappings=[("cloud_in", wiring.points_topic()), ("scan", wiring.scan_topic()), *wiring.TF_REMAPS],
            output="screen",
        ),
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "pcap", default_value="", description="the path of an RS16 recording. Empty = the real device."
            ),
            OpaqueFunction(function=_setup),
        ]
    )
