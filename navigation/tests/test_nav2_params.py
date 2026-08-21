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
        "starten mit ihren Defaults und niemand sagt es.")


def test_the_controller_publishes_stamped_velocity(params):
    assert _node(params, "controller_server")["enable_stamped_cmd_vel"] is True, (
        "Ohne TwistStamped bindet die Subscription des twist_mux nicht. Der "
        "Roboter steht dann still, ohne Fehlermeldung.")


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
    local = params[wiring.NAMESPACE]["local_costmap"]["local_costmap"]["ros__parameters"]
    glob = params[wiring.NAMESPACE]["global_costmap"]["global_costmap"]["ros__parameters"]
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
