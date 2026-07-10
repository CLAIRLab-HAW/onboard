# Husky
After installing the clearpath software stack (see [Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot)), run this line in your user directory:

``
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh && bash -e install-clearpath-custom-setup.sh
``

The installer is interactive and asks (each step `[j/N]`, or pass `-y` to accept all) before optional parts. One of them installs **`ur-dashboard.service`** — it starts the `ur_robot_driver` `dashboard_client` on boot (`power_on`/`brake_release`/`unlock_protective_stop`/`restart_safety`/`get_robot_mode`/`get_safety_mode`), which Clearpath does *not* bring up in the headless setup. The services land under `/a200_0553/manipulators/dashboard_client/*` and are consumed by the `ur_state_manager` package (repo [`ur-state-manager`](https://github.com/CLAIRLab-HAW/ur-state-manager)), which the installer can also clone, build and start on boot (`ur-state-manager.service`).

## `manipulators-watchdog.timer` (late arm power-on + stuck reconnect after restart)

The watchdog covers two cases that are unfixable from a ROS node (both need the dead
driver connection for their own inputs and can't restart the driver process they
depend on), so the installer offers a small **systemd timer** watchdog instead:

**(a) Late arm power-on.** If the UR5 is powered on **long after** the ROS stack booted,
the `ur_robot_driver`'s one-shot ros2_control hardware activation has already failed
against the then-unpowered arm — and ros2_control does **not** retry it. The driver
sits there with a dead hardware component and the pendant stays **"Stopped"**.

**(b) Stuck reconnect after a `clearpath-robot.service` restart with the arm already
powered.** The old `ExternalControl` instance holds the reverse socket; the new driver's
hardware activation fails on the socket collision → `joint_state_broadcaster` stays
inactive → RViz/MoveIt fall back to the URDF default pose (the arm lies **flat**).

The health signal is **the `joint_state_broadcaster` stream**
(`/a200_0553/manipulators/joint_states`), which publishes real arm joints **only** when
the ros2_control hardware interface is activated. `robot_program_running` alone is **not**
a valid health signal — it is the controller-side ExternalControl status (read via
dashboard/RTDE) and stays `true` even when the PC-side motion link is dead, which is
exactly case (b).

Every 10 s (from `OnBootSec=90`) it checks: **arm pingable** (`192.168.131.40`) **but
the JSC stream silent** → it runs `systemctl restart clearpath-manipulators.service`
**once** (cooldown-guarded, state in `/run`, so it can't loop), then powers the arm
(`power_on` + `brake_release`) and restarts `ExternalControl` (`resend_robot_program`).
The restarted driver reconnects, the JSC stream resumes, and `ur_state_manager`'s
`auto_recover` (plus `rg6_control`'s tool-power/prime on the program-running edge) brings
arm **and** gripper up — no manual step. A generous `JS_TIMEOUT` (25 s) grace window
prevents false alarms during the ~15 s the JSC needs to come up after a restart; it stays
silent on a healthy boot (JSC streaming) and while the arm is off (not pingable). Logs:
`journalctl -t manipulators-watchdog -b`; schedule:
`systemctl list-timers manipulators-watchdog.timer`.

## `clearpath-manipulators.service.d/override.conf` (clean driver shutdown)

A drop-in that makes `clearpath-manipulators.service` stop with `KillSignal=SIGINT`
instead of the default `SIGTERM`. `ros2_control_node` / `move_group` / `robot_state_pub`
are ROS nodes and handle `SIGINT` as graceful shutdown (reverse/dashboard sockets closed
in ~1–3 s); under `SIGTERM` the old `ros2_control_node` ignores the signal and lingers up
to 90 s as a zombie still holding the reverse socket — which is what causes the socket
collision in case (b) above. The drop-in layers over the Clearpath-owned unit and
survives package updates.
