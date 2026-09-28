"""Nav2 for the a200-0553.

localization:=none    static_transform_publisher supplies map ─▶ odom
localization:=amcl    AMCL against the stored map (needs scans)
localization:=slam    slam_toolbox maps and supplies map ─▶ odom itself, and the map -- no stored one then
use_sim_time:=true    on the /clock of a simulator plant, whose sensors and TF it stamps

The default is NONE, deliberately: as long as the sensor path delivers no scans, an AMCL in the graph publishes NO
transform at all, the TF chain would stand still, and one would look for the fault in the costmaps.

All topic and frame names come from clair.navigation.wiring.
"""

import os

from launch.actions import DeclareLaunchArgument, OpaqueFunction, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter

from clair.navigation import wiring
from launch import LaunchDescription

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(_HERE, "config", "nav2_params.yaml")
MAPS = os.path.join(_HERE, "maps")
TREES = os.path.join(_HERE, "config", "behavior_trees")

#: The nodes the lifecycle manager has to bring up -- in this order: first
#: the map, then the costmaps, then whatever plans on them.
_CORE_NODES = ["map_server", "controller_server", "planner_server", "behavior_server", "bt_navigator"]

#: Lead time before the lifecycle manager starts configuring.
#:
#: Measured on 2026-08-22: if it starts immediately, the bring-up
#: occasionally fails with
#:   map_server.rclcpp  failed to send response to .../change_state (timeout)
#: and then stalls -- map_server ``inactive``, everything else
#: ``unconfigured``, no navigate_to_pose action.  A second attempt gets
#: through.  So it is a race, not a defect: shortly before, the mock brings
#: up a good two dozen nodes, and the DDS graph is still in motion when the
#: manager expects its first service response.
#:
#: In Jazzy, nav2_lifecycle_manager has NO parameter for this timeout
#: (``ros2 param list`` knows only bond_timeout, bond_respawn_max_duration
#: and attempt_respawn_reconnection -- those take effect only AFTER
#: bring-up).  So one lets the graph settle.  A stack that only sometimes
#: comes up is worse than one that takes eight seconds longer.
_LIFECYCLE_SETTLE_S = 8.0


def _setup(context, *args, **kwargs):
    localization = LaunchConfiguration("localization").perform(context)
    sim_time = LaunchConfiguration("use_sim_time").perform(context) == "true"
    map_file = LaunchConfiguration("map").perform(context)

    common = dict(namespace=wiring.NAMESPACE, output="screen", remappings=wiring.TF_REMAPS)
    # SetParameter reaches every Node after it: a costmap on the wall clock drops a scan stamped by a simulator's
    # /clock as too old, and slam_toolbox never maps.
    nodes = [
        SetParameter("use_sim_time", sim_time),
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            parameters=[PARAMS],
            # By default controller_server publishes on cmd_vel in its own namespace -- that IS the twist_mux input
            # "external".
            **common,
        ),
        Node(package="nav2_planner", executable="planner_server", name="planner_server", parameters=[PARAMS], **common),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            parameters=[PARAMS],
            **common,
        ),
        Node(
            package="nav2_bt_navigator",
            executable="bt_navigator",
            name="bt_navigator",
            # Upstream's trees, recovering on START_OCCUPIED as well (config/behavior_trees says why).
            parameters=[
                PARAMS,
                {
                    "default_nav_to_pose_bt_xml": os.path.join(TREES, "navigate_to_pose_w_replanning_and_recovery.xml"),
                    "default_nav_through_poses_bt_xml": os.path.join(
                        TREES, "navigate_through_poses_w_replanning_and_recovery.xml"
                    ),
                },
            ],
            **common,
        ),
    ]

    managed = list(_CORE_NODES)
    # A stored map, except while slam_toolbox maps: two publishers on one map topic, and the costmap takes whichever
    # came last.
    if localization == "slam":
        managed.remove("map_server")
    else:
        nodes.append(
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                parameters=[PARAMS, {"yaml_filename": os.path.join(MAPS, map_file)}],
                **common,
            )
        )

    if localization == "amcl":
        nodes.append(Node(package="nav2_amcl", executable="amcl", name="amcl", parameters=[PARAMS], **common))
        managed.insert(1, "amcl")
    elif localization == "slam":
        nodes.append(
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                # Jazzy's slam_toolbox is a lifecycle node: on its own it stays unconfigured, publishes no map and no
                # map ─▶ odom, and every costmap waits for the frame (2026-09-27).  The manager brings it up first.
                parameters=[os.path.join(_HERE, "config", "slam_toolbox.yaml"), {"use_lifecycle_manager": True}],
                # It publishes the ABSOLUTE /map, and the costmap listens under the namespace -- the map arrived
                # nowhere (2026-09-27).  The same bend as TF_REMAPS.
                **{
                    **common,
                    "remappings": [*wiring.TF_REMAPS, ("/map", "map"), ("/map_metadata", "map_metadata")],
                },
            )
        )
        managed.insert(0, "slam_toolbox")
    else:
        # Identity map ─▶ odom. The robot therefore drifts against the map, because only the wheel odometry carries it
        # -- that is the deliberate state as long as there are no scans.
        nodes.append(
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="map_to_odom_identity",
                arguments=["--frame-id", "map", "--child-frame-id", "odom"],
                **common,
            )
        )

    nodes.append(
        TimerAction(
            period=_LIFECYCLE_SETTLE_S,
            actions=[
                Node(
                    package="nav2_lifecycle_manager",
                    executable="lifecycle_manager",
                    name="lifecycle_manager_navigation",
                    parameters=[
                        {
                            "autostart": True,
                            "node_names": managed,
                            # Takes effect AFTER bring-up: if a node drops out later, the manager tries to bring it
                            # back in instead of tearing the whole stack down.
                            "attempt_respawn_reconnection": True,
                            "bond_timeout": 10.0,
                        }
                    ],
                    **common,
                )
            ],
        )
    )

    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("localization", default_value="none", choices=["none", "amcl", "slam"]),
            DeclareLaunchArgument("map", default_value="leerer_raum.yaml"),
            DeclareLaunchArgument("use_sim_time", default_value="false", choices=["true", "false"]),
            OpaqueFunction(function=_setup),
        ]
    )
