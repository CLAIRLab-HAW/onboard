"""Nav2-Parameter, die still danebengehen, wenn sie falsch sind.

Der cmd_vel-Typ ist der klassische Fall: twist_mux (use_stamped: True), der
DiffDriveController (use_stamped_vel: True) und das robot-contract-Profil
(cmd_vel_stamped: true) stehen alle auf TwistStamped; Nav2s Jazzy-Default ist
Twist.  Beim falschen Typ bindet die Subscription NICHT -- und niemand meldet
einen Fehler, der Roboter steht einfach.

Braucht weder ROS noch Docker.
"""

from pathlib import Path

import pytest
import yaml

from husky_navigation import wiring

PARAMS_PATH = Path(__file__).resolve().parents[1] / "config" / "nav2_params.yaml"


@pytest.fixture(scope="module")
def params() -> dict:
    return yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))


def _node(params: dict, name: str) -> dict:
    return params[wiring.NAMESPACE][name]["ros__parameters"]


def test_every_node_lives_in_the_robot_namespace(params):
    assert list(params) == [wiring.NAMESPACE], (
        "Nav2-Parameter ausserhalb des Namespace greifen nicht -- die Knoten "
        "starten mit ihren Defaults und niemand sagt es."
    )


# Jeder Nav2-Knoten, der selbst auf cmd_vel schreibt.  Der Parameter gilt PRO
# KNOTEN -- ihn nur beim controller_server zu setzen sieht richtig aus und
# laesst die Recovery-Verhalten trotzdem ins Leere schreiben.  Kommt spaeter
# ein velocity_smoother oder docking_server dazu, gehoert er in diese Liste.
CMD_VEL_PUBLISHERS = ("controller_server", "behavior_server")

# Dieselbe Falle ein zweites Mal: `odom_topic` gilt ebenfalls pro Knoten.  Am
# 2026-08-22 stand er im bt_navigator richtig und im controller_server auf dem
# Nav2-Default "odom" -- ein Topic, auf das niemand publiziert.
ODOM_CONSUMERS = ("controller_server", "bt_navigator")

# Die EKF-Quelle, nicht die rohe des Radcontrollers: der EKF liefert auch die
# TF odom -> base_link, also kommen Pose und Geschwindigkeit von derselben
# Stelle.
EXPECTED_ODOM_TOPIC = "platform/odom/filtered"


@pytest.mark.parametrize("node", ODOM_CONSUMERS)
def test_every_odom_consumer_reads_the_ekf(params, node):
    """Der Default "odom" zeigt auf ein Topic ohne Publisher.

    Das scheitert lautlos: `speed` bleibt 0, und jeder Regler, der die
    Ist-Geschwindigkeit braucht, regelt blind.  Gemessen hat sich das als
    RotationShim gezeigt, der statt 0,8 rad/s nur 0,05 kommandierte -- einen
    einzigen Beschleunigungsschritt, immer wieder von null.
    """
    assert _node(params, node)["odom_topic"] == EXPECTED_ODOM_TOPIC, (
        f"{node} liest ein anderes Odometrie-Topic. Der Nav2-Default 'odom' "
        f"loest im Namespace zu /a200_0553/odom auf -- dort publiziert "
        f"niemand, und es gibt dafuer keine Fehlermeldung."
    )


@pytest.mark.parametrize("node", CMD_VEL_PUBLISHERS)
def test_every_cmd_vel_publisher_is_stamped(params, node):
    """Am 2026-08-22 war genau das falsch, und nichts hat es gemeldet.

    /a200_0553/cmd_vel trug beide Typen: controller_server TwistStamped,
    behavior_server dreimal Twist (einer je Verhalten).  Aufgefallen ist es
    an einer Foxglove-Warnung, nicht an dieser Suite -- ohne Lidar hat die
    Costmap keine Hindernisse, also loest im Mock nie ein Recovery aus, und
    der tote Pfad wurde nie befahren.
    """
    assert _node(params, node)["enable_stamped_cmd_vel"] is True, (
        f"{node} publiziert geometry_msgs/Twist, twist_mux abonniert aber nur "
        "TwistStamped -- die Subscription bindet nicht, und der Roboter steht "
        "still, ohne Fehlermeldung."
    )


def test_both_costmaps_use_the_derived_scan(params):
    for name in ("local_costmap", "global_costmap"):
        costmap = params[wiring.NAMESPACE][name][name]["ros__parameters"]
        assert costmap["obstacle_layer"]["scan"]["topic"] == wiring.scan_topic()


def test_the_robot_radius_covers_the_husky(params):
    """Der Husky ist 0,99 m lang und 0,67 m breit -- ein zu kleiner Radius
    laesst Nav2 Pfade planen, in die der Roboter nicht passt."""
    for name in ("local_costmap", "global_costmap"):
        costmap = params[wiring.NAMESPACE][name][name]["ros__parameters"]
        assert costmap["robot_radius"] >= 0.55


def test_the_costmaps_are_anchored_in_the_documented_frames(params):
    local = params[wiring.NAMESPACE]["local_costmap"]["local_costmap"][
        "ros__parameters"
    ]
    glob = params[wiring.NAMESPACE]["global_costmap"]["global_costmap"][
        "ros__parameters"
    ]
    assert local["global_frame"] == "odom"
    assert glob["global_frame"] == "map"
    assert local["robot_base_frame"] == wiring.BASE_FRAME
    assert glob["robot_base_frame"] == wiring.BASE_FRAME


def test_the_velocity_limits_do_not_exceed_the_controller(params):
    """platform_velocity_controller klemmt bei 1,0 m/s und 1,0 rad/s --
    Nav2 darf nicht mehr befehlen, sonst plant es Bahnen, die der
    Radcontroller stillschweigend beschneidet."""
    ctrl = _node(params, "controller_server")["FollowPath"]
    assert ctrl["max_vel_x"] <= 1.0
    assert ctrl["max_vel_theta"] <= 1.0
