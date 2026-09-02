"""Nav2 drives in the mock -- against a map, WITHOUT localization.

The test name says it outright: in this state the wheel odometry alone carries the robot, it drifts against the map,
and the costmap has no obstacles.  Whoever later takes this test for proof of localization reads it wrong -- that only
the sensor path delivers.

Needs a running container with ``mock platform:=true`` and ``nav``.
"""

import json
import subprocess

import pytest

pytestmark = pytest.mark.nav_e2e

CONTAINER = "husky-offboard-mock-robot-1"


def _exec(script: str, timeout: int = 180) -> str:
    proc = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", script], capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout


@pytest.fixture(scope="module")
def container():
    probe = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"Container {CONTAINER} is not running.")
    if "TARGET=mock" not in probe.stdout:
        pytest.skip("Container is NOT on TARGET=mock -- this test drives the robot.")
    return CONTAINER


def test_the_navigate_to_pose_action_is_offered(container):
    """With retries: the ros2 daemon's discovery is asynchronous.

    A single ``ros2 action list`` right after the start returns an empty list -- not because the action is missing but
    because the daemon does not have its graph yet.  A test that fails on that measures the daemon's start-up time and
    not Nav2.
    """
    out = _exec(
        "source ros-env; "
        "for i in $(seq 1 10); do "
        "  L=$(timeout 20 ros2 action list 2>/dev/null); "
        '  case "$L" in *navigate_to_pose*) echo "$L"; exit 0;; esac; '
        "  sleep 3; "
        'done; echo "$L"',
        timeout=260,
    )
    assert "/a200_0553/navigate_to_pose" in out, (
        "bt_navigator does not offer the action -- did the "
        f"lifecycle_manager come through? Read /tmp/nav.log. Seen:\n{out}"
    )


def test_the_map_is_published(container):
    out = _exec("source ros-env; timeout 10 ros2 topic echo /a200_0553/map --once --field info.resolution 2>/dev/null")
    assert out.strip(), "map_server publishes no map."


def test_the_map_to_base_link_transform_exists(container):
    """With the namespaced TF remaps -- without them tf2_echo reports
    'frame does not exist' and one hunts a transform that is long since
    there."""
    out = _exec(
        "source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
        "map base_link --ros-args "
        "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
        "2>&1 | head -20"
    )
    assert "Translation" in out, (
        "No TF chain map -> base_link. In this state the "
        f"static_transform_publisher supplies map -> odom and the EKF "
        f"odom -> base_link. Output:\n{out}"
    )


def test_navigates_without_localization(container, exclusive_base):
    """A goal 1 m away -- and the odometry says whether it got there.

    Deliberately NOT: 'RViz looks good'.  A running process is no proof, and a pose can look plausible from every
    viewing angle.
    """
    script = r"""
source ros-env
# With retries -- see test_platform_mock_e2e.py: under load the echo
# occasionally comes back empty.
read_x() {
  for _ in 1 2 3 4 5; do
    V=$(timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
          --field pose.pose.position.x 2>/dev/null | head -1)
    case "$V" in ''|*[!0-9.eE+-]*) sleep 2;; *) echo "$V"; return 0;; esac
  done
  echo ""
}
BEFORE=$(read_x)
# The map is 10 x 10 m with its origin in the middle -- x runs from -5 to
# +5.  A goal "always 1 m further ahead" carries the robot out of the map
# after enough test runs, and Nav2 then refuses it (measured on 2026-08-22:
# at x=4.63 all of 0.000 m were driven).  Hence always TOWARDS THE CENTRE.
GOAL=$(python3 -c "import sys; x=float(sys.argv[1]); print(x - 1.0 if x > 0 else x + 1.0)" "$BEFORE")
timeout 120 ros2 action send_goal /a200_0553/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: $GOAL, y: 0.0, z: 0.0},
    orientation: {w: 1.0}}}}" > /tmp/nav_goal.log 2>&1
AFTER=$(read_x)
python3 -c "import json;print(json.dumps({'before': float('''$BEFORE'''), 'after': float('''$AFTER''')}))"
"""
    result = json.loads(_exec(script, timeout=200).strip().splitlines()[-1])
    travelled = abs(result["after"] - result["before"])
    assert travelled > 0.7, (
        f"The goal was 1.0 m away (towards the centre of the map), "
        f"{travelled:.3f} m were driven "
        f"(before {result['before']:.3f}, after {result['after']:.3f}). "
        f"Read /tmp/nav_goal.log in the container."
    )


def test_navigates_to_a_goal_it_has_to_turn_around_for(container, exclusive_base):
    """A goal that demands a large change of direction.

    The neighbouring test deliberately always drives TOWARDS the centre of the map -- that is, practically straight
    ahead.  Exactly for that reason it did not notice on 2026-08-22 that the Husky got stuck on a turn: in the same
    round a goal straight ahead went through in 12 s, while the goal (-2|2) from (1,93|1,78) had travelled all of
    0,06 m after 51 s and then reported ABORTED.

    This test turns the robot away from the goal ON PURPOSE beforehand and checks whether it arrives anyway.  It fails
    if the RotationShimController is missing or the drive does not execute the turn.
    """
    script = r"""
source ros-env
read_odom() {   # -> "x y yaw"
  for _ in 1 2 3 4 5; do
    timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
      --field pose.pose 2>/dev/null | grep -E '^  [xyzw]: ' > /tmp/o.txt
    # pose.pose prints position(x,y,z) then orientation(x,y,z,w) -> 7 value
    # lines, each with TWO leading spaces (looked up with `cat -A` on
    # 2026-08-22; reckoned with four and the grep ran empty).
    if [ "$(wc -l < /tmp/o.txt)" = "7" ]; then
      python3 -c "
import math
v=[float(l.split(': ')[1]) for l in open('/tmp/o.txt')]
px,py,_,qx,qy,qz,qw = v
print('%.4f %.4f %.4f' % (px, py,
      math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))))"
      return 0
    fi
    sleep 2
  done
  echo ""
}
read -r X0 Y0 YAW0 <<< "$(read_odom)"

# Goal direction ALWAYS towards the centre of the map -- otherwise the robot
# wanders out of the 10 m map over many runs and Nav2 refuses the goal.  If
# it already stands almost in the centre, the direction is arbitrary; then +x.
read -r GX GY THETA <<< "$(python3 -c "
import math,sys
x,y = float('$X0'), float('$Y0')
r = math.hypot(x,y)
th = math.atan2(-y,-x) if r > 0.3 else 0.0
print('%.4f %.4f %.4f' % (x+1.2*math.cos(th), y+1.2*math.sin(th), th))")"

# First TURN AWAY: the target heading is theta+pi, that is exactly away from
# the goal.  spin turns RELATIVELY, so compute the difference to the current
# yaw and normalise it onto [-pi,pi].
DELTA=$(python3 -c "
import math
d = ($THETA + math.pi) - $YAW0
while d >  math.pi: d -= 2*math.pi
while d < -math.pi: d += 2*math.pi
print('%.4f' % d)")
timeout 60 ros2 action send_goal /a200_0553/spin nav2_msgs/action/Spin \
  "{target_yaw: $DELTA}" > /dev/null 2>&1

read -r X1 Y1 YAW1 <<< "$(read_odom)"
S=$SECONDS
STATUS=$(timeout 120 ros2 action send_goal /a200_0553/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: $GX, y: $GY, z: 0.0},
    orientation: {w: 1.0}}}}" 2>&1 | grep -oE 'SUCCEEDED|ABORTED|CANCELED' | tail -1)
DUR=$((SECONDS-S))
read -r X2 Y2 YAW2 <<< "$(read_odom)"
python3 -c "
import json,math
print(json.dumps({
  'status': '$STATUS',
  'seconds': $DUR,
  'goal': [$GX, $GY],
  'yaw_before_goal': $YAW1,
  'travelled': math.hypot($X2-($X1), $Y2-($Y1)),
  'remaining': math.hypot($X2-($GX), $Y2-($GY)),
}))"
"""
    result = json.loads(_exec(script, timeout=320).strip().splitlines()[-1])

    assert result["status"] == "SUCCEEDED", (
        f"The goal behind the robot ended with {result['status']!r} after "
        f"{result['seconds']} s; {result['travelled']:.3f} m were driven, "
        f"{result['remaining']:.3f} m are missing. Without the "
        f"RotationShimController the Husky stands still on large changes of "
        f"direction -- check whether FollowPath.plugin is still "
        f"RotationShimController."
    )
    assert result["travelled"] > 0.8, (
        f"Nav2 reports SUCCEEDED, but the odometry sees only "
        f"{result['travelled']:.3f} m -- the goal was 1.2 m away. A success "
        f"without motion is no success."
    )
    assert result["remaining"] < 0.35, (
        f"It has not arrived: {result['remaining']:.3f} m to the goal (xy_goal_tolerance is 0.25)."
    )


def test_the_controller_actually_receives_odometry(container):
    """A configured topic is not yet a data source.

    In ROS 2 a topic already shows up in ``topic list`` when it is merely SUBSCRIBED to.  On 2026-08-22 the
    controller_server was on the default "odom", was the only participant there -- Publisher count: 0 -- and never got
    a velocity.  The static parameter test would not have found that; a wrong topic name looks just like a right one
    there.  Hence here: is there a publisher, and does data arrive?
    """
    topic = _exec(
        "source ros-env; timeout 15 ros2 param get "
        "/a200_0553/controller_server odom_topic 2>/dev/null "
        "| tail -1 | sed 's/.*: //'"
    ).strip()
    assert topic, "odom_topic is not readable on the running controller_server."

    full = topic if topic.startswith("/") else f"/a200_0553/{topic}"
    info = _exec(f"source ros-env; timeout 20 ros2 topic info -v {full} 2>/dev/null | grep 'Publisher count'")
    assert "Publisher count: 0" not in info, (
        f"NOBODY publishes on {full} -- the controller_server never gets its "
        f"actual velocity, `speed` stays 0, and the controller controls "
        f"blind. That shows up as a creeping rotation (0.05 rad/s instead of "
        f"0.8), not as an error message. Seen: {info.strip()!r}"
    )

    sample = _exec(
        f"source ros-env; timeout 8 ros2 topic echo {full} --once --field twist.twist.angular.z 2>/dev/null | head -1"
    )
    assert sample.strip(), f"{full} has a publisher but delivers no data."


def test_the_ground_frame_matches_the_wheel_geometry(container):
    """base_footprint has to sit where the wheels touch the ground.

    The probe joins two sources that know nothing of each other: the URDF (wheel axle, base_footprint) and control.yaml
    (wheel_radius, with which the DiffDriveController computes the odometry).  If they do not match, either the
    rendering is wrong or -- worse -- the odometry, and the latter shows up nowhere.  Whoever switches to outdoor
    wheels, say, and updates only one of the two places gets a failure here instead of a silent driving error.

    Measured on 2026-08-22: wheel axle +0,03282 above base_link, wheel radius 0,1651, base_footprint at -0,13228 --
    exactly the difference.

    What is NOT checked is whether base_footprint lies on the odom plane: the EKF runs with
    ``base_link_frame: base_link`` and ``two_d_mode: True``, so it pins base_link to z=0.  The whole robot therefore
    stands 13,2 cm below the ground plane of the map, which is visible in RViz and Foxglove and looks like a fault.  It
    is Clearpath's convention out of the generated localization.yaml, not settable via robot.yaml, and inconsequential
    for Nav2 -- only x, y and yaw count there.
    """

    def _z(parent: str, child: str) -> float:
        out = _exec(
            f"source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
            f"{parent} {child} --ros-args "
            "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
            "2>&1 | grep -m1 Translation"
        )
        assert "Translation" in out, f"No TF {parent} -> {child}: {out!r}"
        return float(out.split("[")[1].split("]")[0].split(",")[2])

    footprint_z = _z("base_link", "base_footprint")
    axle_z = _z("base_link", "front_left_wheel_link")

    radius = float(
        _exec("grep -m1 'wheel_radius:' /clearpath/platform/config/control.yaml | tr -d ' ' | cut -d: -f2").strip()
    )

    expected = axle_z - radius
    assert abs(footprint_z - expected) < 0.005, (
        f"base_footprint sits at {footprint_z:.5f}, but the wheels touch the "
        f"ground at {expected:.5f} (axle {axle_z:.5f} minus wheel radius "
        f"{radius} from control.yaml). URDF and wheel controller reckon with "
        f"different wheels -- then the odometry is wrong by the same factor "
        f"too, and nobody reports that."
    )
