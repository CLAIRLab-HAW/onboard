"""Sensorpfad des RS16: Treiber + Ableitung des 2D-Scans.

REIN LESEND.  Dieser Launch kommandiert nichts und darf deshalb auch am
Graphen des echten Roboters laufen -- gesperrt wird navigation.launch.py,
weil dessen controller_server auf cmd_vel schreibt.

Aufruf im Container:
    ros2 launch /opt/spact/husky-navigation/launch/lidar.launch.py \
        pcap:=/data/recordings/rs16_labor.pcap     # Mock
    ros2 launch /opt/spact/husky-navigation/launch/lidar.launch.py
                                                   # Geraet (kein pcap-Arg)

Alle Namen kommen aus husky_navigation.wiring -- hier steht keiner ein
zweites Mal (tests/test_launch_files_do_not_restate_the_wiring.py).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from husky_navigation import rslidar_config, wiring


def _setup(context, *args, **kwargs):
    pcap = LaunchConfiguration("pcap").perform(context)
    # rslidar_sdk kennt keine Uebersteuerung einzelner Schluessel -- es liest
    # genau eine Datei.  Die aufgeloeste Fassung entsteht deshalb hier, aus
    # DERSELBEN Vorlage, die auch der Roboter benutzt.
    resolved = rslidar_config.write_resolved(
        "/tmp/rslidar_rs16_resolved.yaml",
        pcap_path=pcap or None,
    )

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
            remappings=[
                ("cloud_in", wiring.points_topic()),
                ("scan", wiring.scan_topic()),
                *wiring.TF_REMAPS,
            ],
            output="screen",
        ),
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "pcap",
                default_value="",
                description="Pfad einer RS16-Aufnahme. Leer = echtes Geraet.",
            ),
            OpaqueFunction(function=_setup),
        ]
    )
