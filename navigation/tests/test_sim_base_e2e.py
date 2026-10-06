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


def _copy(script: str) -> None:
    subprocess.run(["docker", "cp", str(Path(__file__).with_name(script)), f"{CONTAINER}:/tmp/{script}"], check=True)


def _errors_on() -> bool:
    return _exec("cat /tmp/clair-sim-errors 2>/dev/null").strip() != "SIM_ERRORS=off"


def _switch(on: bool) -> None:
    root = Path(__file__).resolve().parents[3]
    subprocess.run([str(root / "deploy/stack/bin/up.sh"), "--sim-errors", "on" if on else "off"], check=True)


def test_the_odometry_overturns_the_world_and_the_imu_pulls_the_ekf_back(sim_stack, exclusive_base):
    """With the errors on the wheels' odometry overturns the world by the slipping skid steer, and the IMU's yaw rate
    pulls the EKF back onto it; off, all three agree.  Measured 2026-10-06 on the MuJoCo stack, one turn each: on
    1.040, 1.117, 1.089 against EKF 1.001, 1.001, 1.000; off 0.9997."""
    _copy("sim_spin.py")
    result = json.loads(_exec("source ros-env; python3 /tmp/sim_spin.py 1 2>/dev/null"))
    if not _errors_on():
        assert result["wheels_over_truth"] == pytest.approx(1.0, abs=0.01)
        assert result["ekf_over_truth"] == pytest.approx(1.0, abs=0.01)
        return
    log = _exec("grep -m1 'the base.s truth on' /tmp/mock.log")
    mean, sigma, odometry = (
        float(v) for v in re.search(r"multiplier ([\d.]+) \+/- ([\d.]+) \(the odometry's ([\d.]+)\)", log).groups()
    )
    assert result["wheels_over_truth"] == pytest.approx(mean / odometry, abs=4 * sigma / odometry)
    # The IMU's yaw rate outweighs the wheels' (the driver's 1.1e-6 against the diff drive's 0.01).
    assert abs(result["ekf_over_truth"] - 1.0) < 0.02
    imu = RobotProfile.load("a200_0553").sim.imu
    assert result["imu_still"]["std_z_rad_s"] == pytest.approx(imu.gyro_noise_rad_s_sqrt_hz / 0.05**0.5, rel=0.3)


def test_one_switch_makes_the_sim_plant_exact_and_errant_again(sim_stack):
    """``up.sh --sim-errors off|on`` on the running stack: the flag, the RS16's ranges and the D435's depth follow.
    Measured 2026-10-06 on the MuJoCo stack: each ray's range scattered by 0.027 m on, 5e-7 m off."""
    _copy("sim_lidar.py")
    _copy("sim_depth.py")
    camera = RobotProfile.load("a200_0553").sim.camera
    before = _errors_on()
    try:
        for on in (False, True):
            _switch(on)
            assert _errors_on() is on
            lidar = json.loads(_exec("source ros-env; python3 /tmp/sim_lidar.py 2>/dev/null"))
            noise_m = RobotProfile.load("a200_0553").sim.lidar.range_noise_m
            # Ten sweeps' standard deviation runs about 8 % under sigma.
            expected = noise_m * 0.92 if on else 0.0
            assert lidar["median_range_std_m"] == pytest.approx(expected, abs=0.005), on
            depth = json.loads(_exec("source ros-env; python3 /tmp/sim_depth.py 2>/dev/null"))
            assert depth["encoding"] == "16UC1", "the RealSense driver's millimeters, whatever the simulator rendered"
            assert depth["valid_share"] > 0.2, "the camera sees something to measure"
            z_m = depth["median_depth_m"]
            sigma_m = z_m**2 * camera.subpixel_rms_px / (camera.depth_focal_px * camera.depth_baseline_m)
            # On: the stereo error at that distance, give or take the millimeter steps; off: the render, steady.
            expected = 0.92 * sigma_m if on else 0.0
            assert depth["median_depth_std_m"] == pytest.approx(expected, abs=max(0.0015, 0.4 * sigma_m)), (on, depth)
    finally:
        _switch(before)
