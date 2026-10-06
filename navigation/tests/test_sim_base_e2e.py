"""A sim plant's world goes where its wheels take it, and its odometry errs against it as a real skid steer's does.

``base-truth`` (deploy/offboard) moves the world by the profile's skid steer, ``imu-sim`` gives the EKF the UM7's yaw
rate.  Needs a running ``up.sh --plant mujoco`` or ``maniskill`` stack; skips on the plain mock, which has neither.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from clair.robot.contract import RobotProfile

pytestmark = pytest.mark.e2e_container_nav

CONTAINER = "offboard-plant-mock-1"
#: The plant's own readers of the ground truth: the IMU, MuJoCo's base follower, the ManiSkill bridge.
PLANT_NODES = {"imu_sim", "mujoco_ros2_control_node", "maniskill_plant"}


def _exec(script: str, timeout: int = 240) -> str:
    return subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-lc", script], capture_output=True, text=True, timeout=timeout
    ).stdout


@pytest.fixture(scope="module")
def sim_stack():
    probe = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"Container {CONTAINER} is not running.")
    if "TARGET=mock" not in probe.stdout:
        pytest.skip("Container is NOT on TARGET=mock -- this test drives the robot.")
    if "Publisher count: 1" not in _exec("source ros-env; ros2 topic info /sim/base_truth 2>&1"):
        pytest.skip("No base-truth: the plain mock, or a stack without the platform.")


def test_only_the_plant_reads_the_ground_truth(sim_stack):
    """Truth is for the plant and evaluation; a Nav2 or agent node subscribed to it would localize by cheating."""
    for topic in ("/sim/base_truth", "/sim/base_pose"):
        info = _exec(f"source ros-env; ros2 topic info -v {topic} 2>&1")
        blocks = info.split("Node name: ")[1:]
        readers = {b.split()[0] for b in blocks if "Endpoint type: SUBSCRIPTION" in b}
        assert readers or topic == "/sim/base_pose", f"nothing reads {topic} -- the world follows nothing:\n{info}"
        assert readers <= PLANT_NODES, f"{topic} is read outside the plant: {readers - PLANT_NODES}"


def test_the_odometry_overturns_the_world_and_the_imu_pulls_the_ekf_back(sim_stack, exclusive_base):
    """Measured 2026-10-06 on the MuJoCo stack, two turns: wheels / truth 1.1003, EKF / truth 0.9937, the still IMU's
    z scattered by 3.8e-4 rad/s."""
    subprocess.run(
        ["docker", "cp", str(Path(__file__).with_name("sim_spin.py")), f"{CONTAINER}:/tmp/sim_spin.py"], check=True
    )
    log = _exec("grep -m1 'the base.s truth on' /tmp/mock.log")
    true_m, odometry_m = (float(v) for v in re.search(r"multiplier ([\d.]+) \(the odometry's ([\d.]+)\)", log).groups())
    result = json.loads(_exec("source ros-env; python3 /tmp/sim_spin.py 1 2>/dev/null"))
    expected = true_m / odometry_m
    assert result["wheels_over_truth"] == pytest.approx(expected, rel=0.01)
    if expected != 1.0:
        # The IMU's yaw rate outweighs the wheels' (the driver's 1.1e-6 against the diff drive's 0.01).
        assert abs(result["ekf_over_truth"] - 1.0) < abs(expected - 1.0) / 3
    imu = RobotProfile.load("a200_0553").sim.imu
    assert result["imu_still"]["std_z_rad_s"] == pytest.approx(imu.gyro_noise_rad_s_sqrt_hz / 0.05**0.5, rel=0.3)
