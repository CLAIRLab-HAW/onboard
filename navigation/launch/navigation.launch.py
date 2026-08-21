"""Nav2 fuer den a200-0553.

localization:=none    static_transform_publisher liefert map -> odom
localization:=amcl    AMCL gegen die gespeicherte Karte (braucht Scans)
localization:=slam    slam_toolbox kartiert und liefert map -> odom selbst

Der Default ist NONE, mit Absicht: solange der Sensorpfad keine Scans
liefert, publiziert ein AMCL im Graphen GAR KEINE Transformation, die
TF-Kette staende still, und man suchte den Fehler in den Costmaps.

Alle Topic- und Framenamen kommen aus husky_navigation.wiring.
"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from husky_navigation import wiring

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(_HERE, "config", "nav2_params.yaml")
MAPS = os.path.join(_HERE, "maps")

#: Die Knoten, die der Lifecycle-Manager hochfahren muss -- in dieser
#: Reihenfolge: erst die Karte, dann die Costmaps, dann, was auf ihnen plant.
_CORE_NODES = ["map_server", "controller_server", "planner_server",
               "behavior_server", "bt_navigator"]


def _setup(context, *args, **kwargs):
    localization = LaunchConfiguration("localization").perform(context)
    map_file = LaunchConfiguration("map").perform(context)

    common = dict(namespace=wiring.NAMESPACE, output="screen",
                  remappings=wiring.TF_REMAPS)
    nodes = [
        Node(package="nav2_map_server", executable="map_server",
             name="map_server",
             parameters=[PARAMS, {"yaml_filename": os.path.join(MAPS, map_file)}],
             **common),
        Node(package="nav2_controller", executable="controller_server",
             name="controller_server", parameters=[PARAMS],
             # controller_server publiziert per Default auf cmd_vel im
             # eigenen Namespace -- das IST der twist_mux-Eingang "external".
             **common),
        Node(package="nav2_planner", executable="planner_server",
             name="planner_server", parameters=[PARAMS], **common),
        Node(package="nav2_behaviors", executable="behavior_server",
             name="behavior_server", parameters=[PARAMS], **common),
        Node(package="nav2_bt_navigator", executable="bt_navigator",
             name="bt_navigator", parameters=[PARAMS], **common),
    ]

    managed = list(_CORE_NODES)

    if localization == "amcl":
        nodes.append(Node(package="nav2_amcl", executable="amcl", name="amcl",
                          parameters=[PARAMS], **common))
        managed.insert(1, "amcl")
    elif localization == "slam":
        nodes.append(Node(package="slam_toolbox",
                          executable="async_slam_toolbox_node",
                          name="slam_toolbox",
                          parameters=[os.path.join(_HERE, "config",
                                                   "slam_toolbox.yaml")],
                          **common))
    else:
        # Identitaet map -> odom. Der Roboter driftet damit gegen die Karte,
        # weil nur die Radodometrie ihn traegt -- das ist der bewusste Stand,
        # solange es keine Scans gibt.
        nodes.append(Node(
            package="tf2_ros", executable="static_transform_publisher",
            name="map_to_odom_identity",
            arguments=["--frame-id", "map", "--child-frame-id", "odom"],
            **common))

    nodes.append(Node(
        package="nav2_lifecycle_manager", executable="lifecycle_manager",
        name="lifecycle_manager_navigation",
        parameters=[{"autostart": True, "node_names": managed}],
        **common))

    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("localization", default_value="none",
                              choices=["none", "amcl", "slam"]),
        DeclareLaunchArgument("map", default_value="leerer_raum.yaml"),
        OpaqueFunction(function=_setup),
    ])
