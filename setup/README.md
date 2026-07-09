# Husky
After installing the clearpath software stack (see [Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot)), run this line in your user directory:

``
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh && bash -e install-clearpath-custom-setup.sh
``

The installer is interactive and asks (each step `[j/N]`, or pass `-y` to accept all) before optional parts. One of them installs **`ur-dashboard.service`** — it starts the `ur_robot_driver` `dashboard_client` on boot (`power_on`/`brake_release`/`unlock_protective_stop`/`restart_safety`/`get_robot_mode`/`get_safety_mode`), which Clearpath does *not* bring up in the headless setup. The services land under `/a200_0553/manipulators/dashboard_client/*` and are consumed by the `ur_state_manager` package (repo [`ur-state-manager`](https://github.com/CLAIRLab-HAW/ur-state-manager)), which the installer can also clone, build and start on boot (`ur-state-manager.service`).

## `manipulators-watchdog.timer` (late arm power-on)

If the UR5 is powered on **long after** the ROS stack booted, the `ur_robot_driver`'s
one-shot ros2_control hardware activation has already failed against the then-unpowered
arm — and ros2_control does **not** retry it. The driver then sits there **not**
publishing `robot_program_running`, so `dashboard_client`/`ur_state_manager` have no
input and the pendant stays **"Stopped"**. This is unfixable from a ROS node (it needs
the dead driver connection for its own inputs and can't restart the driver process it
depends on) — so the installer offers a small **systemd timer** watchdog instead.

Every 30 s (from `OnBootSec=90`) it checks: **arm pingable** (`192.168.131.40`) **but
`robot_program_running` not publishing** → it runs `systemctl restart
clearpath-manipulators.service` **once** (cooldown-guarded, state in `/run`, so it can't
loop). The restarted driver reconnects to the now-powered arm, `robot_program_running`
resumes, and `ur_state_manager`'s `auto_recover` (plus `rg6_control`'s tool-power/prime
on the program-running edge) brings arm **and** gripper up — no manual step. It stays
silent on a healthy boot (arm already up → topic publishes) and while the arm is off
(not pingable). Logs: `journalctl -t manipulators-watchdog -b`; schedule:
`systemctl list-timers manipulators-watchdog.timer`. The `Restart=on-failure` on the
driver service is **not** enough here — the driver doesn't crash, it just sits with a
dead hardware component, so nothing triggers a restart; the watchdog polls the actual
state instead.
