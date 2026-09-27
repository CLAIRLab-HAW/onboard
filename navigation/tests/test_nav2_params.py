"""Nav2 parameters that go silently wrong when they are set wrong.

The cmd_vel type is the classic case: twist_mux (use_stamped: True), the DiffDriveController (use_stamped_vel: True)
and the robot-contract profile (cmd_vel_stamped: true) are all on TwistStamped; Nav2's Jazzy default is Twist.  With
the wrong type the subscription does NOT bind -- and nobody reports an error, the robot simply stands still.

Needs neither ROS nor Docker.
"""

from pathlib import Path

import pytest
import yaml

from clair.navigation import wiring

PARAMS_PATH = Path(__file__).resolve().parents[1] / "config" / "nav2_params.yaml"


@pytest.fixture(scope="module")
def params() -> dict:
    return yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))


def _node(params: dict, name: str) -> dict:
    return params[wiring.NAMESPACE][name]["ros__parameters"]


def test_every_node_lives_in_the_robot_namespace(params):
    assert list(params) == [wiring.NAMESPACE], (
        "Nav2 parameters outside the namespace do not take effect -- the "
        "nodes start with their defaults and nobody says so."
    )


# Every Nav2 node that writes to cmd_vel itself.  The parameter applies PER NODE -- setting it only on the
# controller_server looks right and still lets the recovery behaviours write into the void.  If a velocity_smoother or
# docking_server is added later, it belongs in this list.
CMD_VEL_PUBLISHERS = ("controller_server", "behavior_server")

# The same trap a second time: ``odom_topic`` likewise applies per node.  On 2026-08-22 it was right in the
# bt_navigator and on the Nav2 default "odom" in the controller_server -- a topic nobody publishes to.
ODOM_CONSUMERS = ("controller_server", "bt_navigator")

# The EKF source, not the raw one from the wheel controller: the EKF also supplies the TF odom ─▶ base_link, so pose
# and velocity come from the same place.
EXPECTED_ODOM_TOPIC = "platform/odom/filtered"


@pytest.mark.parametrize("node", ODOM_CONSUMERS)
def test_every_odom_consumer_reads_the_ekf(params, node):
    """The default "odom" points at a topic without a publisher.

    That fails silently: ``speed`` stays 0, and every controller that needs the actual velocity controls blind.  In
    the measurement it showed up as a RotationShim that commanded only 0,05 rad/s instead of 0,8 -- a single
    acceleration step, over and over from zero.
    """
    assert _node(params, node)["odom_topic"] == EXPECTED_ODOM_TOPIC, (
        f"{node} reads a different odometry topic. The Nav2 default 'odom' "
        f"resolves to /a200_0553/odom inside the namespace -- nobody "
        f"publishes there, and there is no error message for it."
    )


@pytest.mark.parametrize("node", CMD_VEL_PUBLISHERS)
def test_every_cmd_vel_publisher_is_stamped(params, node):
    """On 2026-08-22 exactly this was wrong, and nothing reported it.

    /a200_0553/cmd_vel carried both types: controller_server TwistStamped, behavior_server three times Twist (one per
    behaviour).  It was noticed through a Foxglove warning, not through this suite -- without a lidar the costmap has
    no obstacles, so in the mock a recovery never triggers, and the dead path was never travelled.
    """
    assert _node(params, node)["enable_stamped_cmd_vel"] is True, (
        f"{node} publishes geometry_msgs/Twist, but twist_mux subscribes only "
        "to TwistStamped -- the subscription does not bind, and the robot "
        "stands still, without an error message."
    )


def test_both_costmaps_mark_and_clear_from_the_lidars_points(params):
    """The RS16's own points, not the scan derived from them: a voxel layer sees the heights the scan's band drops."""
    for name in ("local_costmap", "global_costmap"):
        layer = params[wiring.NAMESPACE][name][name]["ros__parameters"]["obstacle_layer"]
        sources = layer["observation_sources"].split()
        assert {layer[s]["topic"] for s in sources} == {wiring.points_topic()}
        assert any(layer[s]["marking"] for s in sources) and any(layer[s]["clearing"] for s in sources)


def test_the_footprint_covers_the_husky(params):
    """The Husky is 0,99 m long and 0,67 m wide -- too small a footprint lets
    Nav2 plan paths the robot does not fit through."""
    import ast

    for name in ("local_costmap", "global_costmap"):
        costmap = params[wiring.NAMESPACE][name][name]["ros__parameters"]
        corners = ast.literal_eval(costmap["footprint"])
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        assert min(xs) <= -0.495 and max(xs) >= 0.495 and min(ys) <= -0.335 and max(ys) >= 0.335
        assert "robot_radius" not in costmap, "a radius beside a footprint -- which one counts?"


def test_the_costmaps_are_anchored_in_the_documented_frames(params):
    local = params[wiring.NAMESPACE]["local_costmap"]["local_costmap"]["ros__parameters"]
    glob = params[wiring.NAMESPACE]["global_costmap"]["global_costmap"]["ros__parameters"]
    assert local["global_frame"] == "odom"
    assert glob["global_frame"] == "map"
    assert local["robot_base_frame"] == wiring.BASE_FRAME
    assert glob["robot_base_frame"] == wiring.BASE_FRAME


def test_the_velocity_limits_do_not_exceed_the_controller(params):
    """platform_velocity_controller clamps at 1,0 m/s and 1,0 rad/s -- Nav2
    must not command more, otherwise it plans trajectories the wheel
    controller silently trims."""
    ctrl = _node(params, "controller_server")["FollowPath"]
    assert ctrl["max_vel_x"] <= 1.0
    assert ctrl["max_vel_theta"] <= 1.0


def test_both_costmaps_see_the_lidars_points_up_to_above_the_arm(params):
    """A tabletop stands above the scan's height band; only the points in a voxel layer keep it marked."""
    for name in ("local_costmap", "global_costmap"):
        layer = params[wiring.NAMESPACE][name][name]["ros__parameters"]["obstacle_layer"]
        assert layer["plugin"] == "spatio_temporal_voxel_layer/SpatioTemporalVoxelLayer"
        assert layer["points_mark"]["min_obstacle_height"] > 0.0, "the floor is no obstacle"
        assert layer["points_mark"]["max_obstacle_height"] >= 1.2, "a tabletop meets the arm at ~0.75 m"


def test_a_mark_the_lidar_no_longer_sees_decays(params):
    """The RS16's 16 rings seldom pass through an old mark, so only decay clears most of them: 0.8 % of the global
    costmap was free after some driving with a voxel layer that kept its marks (2026-09-27)."""
    for name in ("local_costmap", "global_costmap"):
        layer = params[wiring.NAMESPACE][name][name]["ros__parameters"]["obstacle_layer"]
        assert layer["decay_model"] == 0 and 0.0 < layer["voxel_decay"] <= 30.0
        clear = layer["points_clear"]
        assert clear["model_type"] == 1, "the frustum of a 3D lidar, not of a depth camera"
        assert clear["horizontal_fov_angle"] >= 6.28, "all the way around"


def test_the_skid_steer_never_turns_on_the_spot_and_may_back_out(params):
    """The a200 drives arcs forward and backward and does not spin in place: the planner is kinematic (Reeds-Shepp),
    the controller reverses and never rotates to a heading, and no recovery spins."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    ns = params[wiring.NAMESPACE]
    planner = ns["planner_server"]["ros__parameters"]["GridBased"]
    assert planner["plugin"] == "nav2_smac_planner::SmacPlannerHybrid"
    assert planner["motion_model_for_search"] == "REEDS_SHEPP"
    follow = ns["controller_server"]["ros__parameters"]["FollowPath"]
    assert follow["plugin"] == "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
    assert follow["allow_reversing"] is True and follow["use_rotate_to_heading"] is False
    # The planner's tightest arc is one the controller can drive at its desired speed.
    assert planner["minimum_turning_radius"] >= follow["desired_linear_vel"] / follow["max_vel_theta"] - 1e-9
    trees = sorted((Path(__file__).resolve().parents[1] / "config" / "behavior_trees").glob("*.xml"))
    assert len(trees) == 2
    for tree in trees:
        assert not [e for e in ET.parse(tree).getroot().iter() if e.tag == "Spin"], tree.name
