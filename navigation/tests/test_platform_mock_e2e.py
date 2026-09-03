"""The base has to really move in the mock -- not just turn wheels.

The expensive misjudgement here is NOT "it does not drive" but "the wheels turn in RViz and the odometry reports
standstill".  That looks like a Nav2 fault and is a URDF fault (missing calculate_dynamics). This test therefore checks
the ODOMETRY, not the wheel joints.

Needs a running container with ``mock platform:=true``.
"""

import json
import subprocess

import pytest

pytestmark = pytest.mark.e2e_container_nav

CONTAINER = "offboard-plant-mock-1"


def _exec(script: str, timeout: int = 90) -> str:
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
        pytest.skip("Container is NOT on TARGET=mock -- this test commands cmd_vel and would drive the real Husky.")
    return CONTAINER


def test_the_platform_controller_is_active(container):
    out = _exec("source ros-env; ros2 control list_controllers -c /a200_0553/controller_manager 2>/dev/null")
    assert "platform_velocity_controller" in out, (
        "The wheel controller is not loaded -- was `mock platform:=true` started?"
    )
    assert "active" in out


def test_only_the_platform_hardware_is_claimed_by_the_platform_manager(container):
    """The risk from spec paragraph 3.4: a controller_manager loads ALL
    ros2_control blocks of the URDF it is given."""
    out = _exec("source ros-env; ros2 control list_hardware_components -c /a200_0553/controller_manager 2>/dev/null")
    assert "a200_hardware" in out
    assert "arm_0" not in out, (
        "The platform manager claims the arm hardware as well -- then two "
        "controller_managers quarrel over the same joints. Way out: an own "
        "URDF processed with use_manipulation_controllers:=false, passed as "
        "a parameter (spec paragraph 3.4)."
    )


def test_driving_forward_moves_the_odometry(container, exclusive_base):
    """The core: cmd_vel in, distance travelled out."""
    script = r"""
source ros-env
# head -1: `--once` appends a "---" line on which float() fails.
#
# With retries: under load (mock + Nav2 = a good three dozen nodes) the echo
# occasionally comes back empty, and float("") ends the measurement with an
# error that looks like "no odometry" and is none.  Five attempts, then it is
# really silent.
read_x() {
  for _ in 1 2 3 4 5; do
    V=$(timeout 8 ros2 topic echo /a200_0553/platform/odom --once \
          --field pose.pose.position.x 2>/dev/null | head -1)
    case "$V" in ''|*[!0-9.eE+-]*) sleep 2;; *) echo "$V"; return 0;; esac
  done
  echo ""
}
BEFORE=$(read_x)
# Direction ALWAYS towards the centre of the map.  If the test always drives
# forwards, the robot wanders out of the 10 m map over many runs -- measured
# on 2026-08-22: at x=4.63 Nav2 refused the next goal and the neighbouring
# test measured 0.000 m.  This way it stays repeatable as often as you like.
VX=$(python3 -c "import sys; print(-0.2 if float(sys.argv[1]) > 0 else 0.2)" "$BEFORE")
# Drive window 8 s, measurement threshold 0.3 m -- deliberately far apart.
#
# Under load `ros2 topic pub` needs one to two seconds until the first
# command is on the wire (create node, discovery).  With `timeout 3` barely
# 1 s of driving was left of that, and the test measured 0.155-0.18 m instead
# of 0.6 m -- so it measured the start-up time of the CLI, not the base.
# Reproduced three times on 2026-08-22.
#
# 8 s yield around 1.2 m even with 2 s of start-up.  The threshold stays at
# 0.3 m: far above the encoder drift (~0.01 rad) and far below the expected
# value, so insensitive to load and still meaningful.
timeout 8 ros2 topic pub -r 20 /a200_0553/cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: base_link}, twist: {linear: {x: $VX}}}" > /dev/null 2>&1
sleep 1
AFTER=$(read_x)
python3 -c "import json;print(json.dumps({'before': float('''$BEFORE'''), 'after': float('''$AFTER''')}))"
"""
    result = json.loads(_exec(script).strip().splitlines()[-1])
    travelled = abs(result["after"] - result["before"])
    assert travelled > 0.3, (
        f"0.2 m/s over 8 s should yield around 1.2 m (threshold 0.3 m), "
        f"measured were "
        f"{travelled:.3f} m (before {result['before']:.3f}, after "
        f"{result['after']:.3f}). If the value stays at 0, "
        f"calculate_dynamics is missing on the mock hardware."
    )


def test_the_odom_to_base_link_transform_exists(container):
    """The TF remaps are no detail here, they are the whole test.

    tf2 broadcasts on the ABSOLUTE names /tf and /tf_static; the graph of this robot however keeps them under
    /a200_0553/tf.  A tf2_echo without these remaps reports 'Invalid frame ID "odom" ... frame does not exist' -- that
    looks like a missing transform and is a mishearing.
    """
    out = _exec(
        "source ros-env; timeout 10 ros2 run tf2_ros tf2_echo "
        "odom base_link --ros-args "
        "-r /tf:=/a200_0553/tf -r /tf_static:=/a200_0553/tf_static "
        "2>&1 | head -20"
    )
    assert "Translation" in out, (
        "No TF edge odom -> base_link. It comes from the ekf_node, NOT from "
        "the wheel controller (enable_odom_tf: False in control.yaml) -- is "
        f"the EKF running? Output:\n{out}"
    )
