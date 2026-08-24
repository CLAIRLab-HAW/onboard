"""Nav2 fuer den a200-0553.

localization:=none    static_transform_publisher liefert map -> odom
localization:=amcl    AMCL gegen die gespeicherte Karte (braucht Scans)
localization:=slam    slam_toolbox kartiert und liefert map -> odom selbst

Der Default ist NONE, mit Absicht: solange der Sensorpfad keine Scans liefert, publiziert ein AMCL im Graphen GAR KEINE
Transformation, die TF-Kette staende still, und man suchte den Fehler in den Costmaps.

Alle Topic- und Framenamen kommen aus husky_navigation.wiring.
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from husky_navigation import wiring

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(_HERE, "config", "nav2_params.yaml")
MAPS = os.path.join(_HERE, "maps")

#: Die Knoten, die der Lifecycle-Manager hochfahren muss -- in dieser
#: Reihenfolge: erst die Karte, dann die Costmaps, dann, was auf ihnen plant.
_CORE_NODES = ["map_server", "controller_server", "planner_server", "behavior_server", "bt_navigator"]

#: Vorlauf, bevor der Lifecycle-Manager zu konfigurieren beginnt.
#:
#: Am 2026-08-22 gemessen: startet er sofort, scheitert der Hochlauf
#: gelegentlich mit
#:   map_server.rclcpp  failed to send response to .../change_state (timeout)
#: und bleibt dann stehen -- map_server 'inactive', alle anderen
#: 'unconfigured', keine navigate_to_pose-Action.  Ein zweiter Anlauf kommt
#: durch.  Es ist also ein Rennen, kein Defekt: der Mock zieht kurz zuvor gut
#: zwei Dutzend Knoten hoch, und der DDS-Graph ist noch in Bewegung, wenn der
#: Manager seine erste Service-Antwort erwartet.
#:
#: nav2_lifecycle_manager hat in Jazzy KEINEN Parameter fuer dieses Timeout
#: (`ros2 param list` kennt nur bond_timeout, bond_respawn_max_duration und
#: attempt_respawn_reconnection -- die greifen erst NACH dem Hochlauf).  Also
#: laesst man den Graphen sich setzen.  Ein Stack, der nur manchmal
#: hochkommt, ist schlimmer als einer, der acht Sekunden laenger braucht.
_LIFECYCLE_SETTLE_S = 8.0


def _setup(context, *args, **kwargs):
    localization = LaunchConfiguration("localization").perform(context)
    map_file = LaunchConfiguration("map").perform(context)

    common = dict(namespace=wiring.NAMESPACE, output="screen", remappings=wiring.TF_REMAPS)
    nodes = [
        Node(
            package="nav2_map_server",
            executable="map_server",
            name="map_server",
            parameters=[PARAMS, {"yaml_filename": os.path.join(MAPS, map_file)}],
            **common
        ),
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            parameters=[PARAMS],
            # controller_server publiziert per Default auf cmd_vel im eigenen Namespace -- das IST der twist_mux-Eingang
            # "external".
            **common
        ),
        Node(package="nav2_planner", executable="planner_server", name="planner_server", parameters=[PARAMS], **common),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            parameters=[PARAMS],
            **common
        ),
        Node(
            package="nav2_bt_navigator", executable="bt_navigator", name="bt_navigator", parameters=[PARAMS], **common
        ),
    ]

    managed = list(_CORE_NODES)

    if localization == "amcl":
        nodes.append(Node(package="nav2_amcl", executable="amcl", name="amcl", parameters=[PARAMS], **common))
        managed.insert(1, "amcl")
    elif localization == "slam":
        nodes.append(
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                parameters=[os.path.join(_HERE, "config", "slam_toolbox.yaml")],
                **common
            )
        )
    else:
        # Identitaet map -> odom. Der Roboter driftet damit gegen die Karte, weil nur die Radodometrie ihn traegt -- das
        # ist der bewusste Stand, solange es keine Scans gibt.
        nodes.append(
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="map_to_odom_identity",
                arguments=["--frame-id", "map", "--child-frame-id", "odom"],
                **common
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
                            # Greift NACH dem Hochlauf: faellt ein Knoten spaeter weg, versucht der Manager ihn wieder
                            # einzubinden, statt den ganzen Stack abzuraeumen.
                            "attempt_respawn_reconnection": True,
                            "bond_timeout": 10.0,
                        }
                    ],
                    **common
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
            OpaqueFunction(function=_setup),
        ]
    )
