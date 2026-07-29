# Husky
After installing the clearpath software stack (see [Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot)), run this line in your user directory:

``
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh && bash -e install-clearpath-custom-setup.sh
``

The installer is interactive and asks (each step `[j/N]`, or pass `-y` to accept all) before optional parts. One of them installs **`clearpath-custom-ur-dashboard.service`** — it starts the `ur_robot_driver` `dashboard_client` on boot (`power_on`/`brake_release`/`unlock_protective_stop`/`restart_safety`/`get_robot_mode`/`get_safety_mode`), which Clearpath does *not* bring up in the headless setup. The services land under `/a200_0553/manipulators/dashboard_client/*` and are consumed by the `ur_state_manager` package (repo [`ur-state-manager`](https://github.com/CLAIRLab-HAW/ur-state-manager)), which the installer can also clone, build and start on boot (`clearpath-custom-ur-state-manager.service`).

All custom units the installer creates carry the `clearpath-custom-*` prefix (`clearpath-custom-rg6-bringup`, `clearpath-custom-joint-states`, `clearpath-custom-arm-controllers`, `clearpath-custom-ur-dashboard`, `clearpath-custom-ur-state-manager`, `clearpath-custom-robot-yaml-update`, `clearpath-custom-manipulator-diagnostics`, `clearpath-custom-manipulators-watchdog.service`/`.timer`, plus `clearpath-custom-setup`). A re-run on a host that still has the old, unprefixed names disables and removes them first (migration window: those services stop briefly, then the renamed ones start). Drop-ins on Clearpath-owned units (`clearpath-manipulators.service.d/override.conf`) keep their target-unit name by systemd convention.

## `clearpath-custom-manipulators-watchdog.timer` (late arm power-on + stuck reconnect after restart)

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
the JSC stream silent** → if the arm is **not** `POWER_OFF`, it runs
`systemctl restart clearpath-manipulators.service` **once** (cooldown-guarded, state in
`/run`, so it can't loop) and restarts `ExternalControl` (`resend_robot_program`). It
does **not** power the arm (`power_on`/`brake_release`) — powering is an operator
decision (protecting maintenance / end-of-day shutdown); if the arm is `POWER_OFF`, no
recovery runs (no driver-restart loop against an unpowered arm). Once the operator
powers the arm, the watchdog reconnects the motion link on the next tick. Protective /
safety stops (`safety_mode != NORMAL`) are **not** auto-cleared — `resend` is skipped,
manual clear required. The restarted driver reconnects, the JSC stream resumes, and
`ur_state_manager`'s `auto_recover` (plus `rg6_control`'s tool-power/prime on the
program-running edge) brings the **gripper** up once the arm is powered and the program
runs. A generous `JS_TIMEOUT` (25 s) grace window prevents false alarms during the ~15 s
the JSC needs to come up after a restart; it stays silent on a healthy boot (JSC
streaming) and while the arm is off (not pingable). Logs:
`journalctl -t manipulators-watchdog -b`; schedule:
`systemctl list-timers clearpath-custom-manipulators-watchdog.timer`.

## `clearpath-manipulators.service.d/override.conf` (clean driver shutdown)

A drop-in that makes `clearpath-manipulators.service` stop with `KillSignal=SIGINT`
instead of the default `SIGTERM`. `ros2_control_node` / `move_group` / `robot_state_pub`
are ROS nodes and handle `SIGINT` as graceful shutdown (reverse/dashboard sockets closed
in ~1–3 s); under `SIGTERM` the old `ros2_control_node` ignores the signal and lingers up
to 90 s as a zombie still holding the reverse socket — which is what causes the socket
collision in case (b) above. The drop-in layers over the Clearpath-owned unit and
survives package updates.

## `clearpath-custom-manipulator-diagnostics.service` (UR5 + RG6 in Cockpit)

Cockpit zeigt über die Erweiterung
[`cockpit-ros2-diagnostics`](https://github.com/clearpathrobotics/cockpit-ros2-diagnostics)
den Inhalt von `<ns>/diagnostics_agg`. **Der Manipulator fehlt dort komplett** —
und zwar an drei Stellen gleichzeitig:

* `clearpath_generator_common` erzeugt Analyzer nur für Platform (Power, E-Stop,
  Drive) und Sensoren; Arm/Greifer kommen im Generator gar nicht vor.
* Der `controller_manager` des Arms publiziert seine Diagnose in den
  *manipulators*-Namespace (`/a200_0553/manipulators/diagnostics`) — nicht auf
  `/a200_0553/diagnostics`, das der Aggregator abonniert.
* `ur_robot_driver` und `rg6_control` liefern ihren Zustand als
  `ur_dashboard_msgs` bzw. `rg6_msgs/GripperState`, nicht als `diagnostic_msgs`.

Drei Bausteine schließen die Lücke, alle vom Installer (optionale Schritte):

1. **`manipulator-diagnostics`** (`scripts/manipulator_diagnostics.py`,
   root-eigene Kopie unter `/usr/local/bin`, Wrapper sourct zusätzlich den
   `onrobot-rg6`-Workspace für `rg6_msgs`): publiziert mit 1 Hz fünf Status auf
   `/a200_0553/diagnostics`:

   | Status | Inhalt |
   |---|---|
   | `Arm Mode` | `robot_mode` + `safety_mode` (latched Topics des `io_and_status_controller`) |
   | `Arm Control` | **der belastbare Gesundheitsindikator**: läuft der joint\_state-Strom? |
   | `Arm Joints` | Gelenkwinkel (rad + °), Geschwindigkeit, Effort, Rate |
   | `Arm Controllers` | `controller_manager/list_controllers` — welcher Kommando-Controller ist aktiv |
   | `Gripper` | RG6: Weite (m/mm/%), Kraftsignal, `grip_detected`, `busy`, Tool-Power, letzter Befehl |

   `Arm Control` bewertet bewusst den **joint\_state-Strom**, nicht
   `robot_program_running`: letzteres bleibt `true`, während die PC-seitige
   Motion-Link tot ist — genau der Fall (b) des Watchdogs oben. Selbsttest ohne
   ROS: `python3 /usr/local/bin/manipulator-diagnostics --selftest`.

2. **Boot-Patcher Schritt 6** (`clearpath-custom-setup.py`,
   `add_manipulator_analyzers`): trägt idempotent eine AnalyzerGroup
   `Manipulator` mit den Untergruppen `Arm` und `Gripper` in das generierte
   `/etc/clearpath/platform/config/diagnostic_aggregator.yaml` ein — **nur**
   wenn die Unit-Datei existiert (die Datei ist der Feature-Schalter, wie beim
   octomap-feed). Die Analyzer listen ihre Status als `expected`: stirbt der
   Node, bleiben sie als **STALE** in der Anzeige stehen statt spurlos zu
   verschwinden.

3. **Cockpit-Plugin-Fork**
   ([`CLAIRLab-HAW/cockpit-ros2-diagnostics`](https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics),
   lokal `robot/cockpit-ros2-diagnostics`): zusätzlich zum generischen Baum ein
   **Manipulator-Panel** (Arm-Karte mit Mode-/Safety-/ExternalControl-/
   Motion-Link-Badges, Gelenktabelle und Controller-Chips; Greifer-Karte mit
   Öffnungs-Balken, `grip_detected`, Tool-Power, letztem Befehl). Das Panel
   liest denselben `diagnostics_agg`-Strom, den die Erweiterung ohnehin
   abonniert — keine zusätzliche Topic-Subscription, also gelten Pause,
   History und Reconnect unverändert. Ohne Manipulator-Status im Baum rendert
   es **gar nichts** (Roboter ohne Arm bleiben unverändert).

   Installiert wird nach `/usr/local/share/cockpit/ros2-diagnostics`. Cockpit
   sucht in der Reihenfolge `~/.local/share/cockpit`, `/etc/cockpit`,
   `/usr/local/share/cockpit`, `/usr/share/cockpit` — der Fork **überdeckt**
   damit das apt-Paket, ohne es zu ersetzen. Rückbau: Verzeichnis löschen, das
   Original ist sofort wieder aktiv (kein apt nötig). Umgekehrt gilt: solange
   der Fork liegt, sind apt-Updates von `cockpit-ros2-diagnostics` nicht mehr
   sichtbar — Fork bei Bedarf nachziehen.

   **Der Installer installiert kein nodejs.** Er nimmt ein vorgebautes `dist/`
   aus dem Checkout; fehlt es und sind `npm`+`make` vorhanden, baut er auf dem
   Roboter, sonst bricht er diesen Schritt mit Anleitung ab. Empfohlener Weg
   (Roboter bleibt toolchain-frei):

   ```bash
   git clone https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics.git
   cd cockpit-ros2-diagnostics && make
   rsync -a dist/ robot@<robot>:~/cockpit-ros2-diagnostics/dist/
   ```

**Verifikation nach Install + Reboot (Checkliste):**

1. `journalctl -u clearpath-custom-manipulator-diagnostics -b` → Startzeile mit
   Namespace/Topic/Rate.
2. `journalctl -t clearpath-custom-setup -b | grep -i manipulator` →
   „Analyzer-Gruppe 'Manipulator' … eingetragen" (bzw. „bereits korrekt").
3. `ros2 topic echo /a200_0553/diagnostics_agg --once` → Einträge unter
   `/Clearpath Diagnostics/Manipulator/Arm/…` und `…/Gripper`.
4. Cockpit (`http://<robot>:9090` → ROS 2 Diagnostics): Karte **Manipulator**
   mit Arm- und Greifer-Kachel.
5. Funktionsprobe: Greifer öffnen/schließen → Balken + `grip_detected` folgen;
   Arm stromlos schalten → `Arm Mode` wird WARN/ERROR, `Arm Control` meldet den
   abgerissenen joint\_state-Strom.
6. Rückbau-Probe: `systemctl disable --now
   clearpath-custom-manipulator-diagnostics`, Unit-Datei löschen, Reboot → die
   Analyzer verschwinden wieder aus der generierten YAML (`.bak` liegt daneben),
   das Panel rendert nichts mehr.

## `clearpath-custom-octomap-feed.service` (MoveIt-Octomap: dichte Hindernis-Schicht)

Schritt 2 der HRL-Hindernis-Architektur (Schritt 1 = objekt-basierte Boxen vom
Offboard-Client über `/twin/scene_update`): `move_group` pflegt über seinen
**Occupancy Map Monitor** (`PointCloudOctomapUpdater`) einen probabilistischen
Voxel-Octree aus der Wrist-D435 und weicht damit auch Hindernissen aus, die der
Objekt-Tracker nicht (oder noch nicht) kennt. Raycasts räumen freigewordenen
Raum automatisch — die „Frische“ ist damit sensor-getaktet statt heuristisch.

Zwei Bausteine, beide vom Installer (optionaler Schritt):

1. **`octomap-feed`** (`scripts/octomap_feed.py`, root-eigene Kopie unter
   `/usr/local/bin`): drosselt das 30-fps-Depth der Kamera auf ~5 Hz, subsampled
   (stride 2) und publiziert `…/sensors/camera_0/octomap_points`
   (PointCloud2 im optischen Frame; QoS RELIABLE, matcht jeden Subscriber).
   Selbsttest ohne ROS: `python3 /usr/local/bin/octomap-feed --selftest`.
2. **Boot-Patcher Schritt 5** (`clearpath-custom-setup.py`,
   `add_octomap_sensor_params`): trägt die Sensor-Parameter idempotent in das
   generierte `/etc/clearpath/manipulators/config/moveit.yaml` ein — **nur**
   wenn die Unit-Datei existiert (die Datei ist der Feature-Schalter).
   `octomap_frame` ist bewusst `base_link` (odom ist auf diesem Roboter
   UTM-gestützt und springt), `octomap_resolution` 0.025, `max_range` 2.0.

**Zusammenspiel mit den Objekt-Collision-Objects:** MoveIts
PlanningSceneMonitor maskiert bekannte World-Objects und attachte Bodies aus
dem Octree (`excludeWorldObjectsFromOctree` / `excludeAttachedBodiesFromOctree`)
— die vom Mac gepushten Würfel, der Boden-Slab und die Hindernis-Boxen erzeugen
also keine blockierenden Voxel; Griffe bleiben planbar. Der Roboter selbst wird
vom Updater geometrisch selbst-gefiltert (`padding_offset` 0.03).

**Voraussetzung (bewusst NICHT vom Installer erledigt):** der
`PointCloudOctomapUpdater` kommt aus **`ros-jazzy-moveit-ros-perception`** —
auf a200-0553 Stand 2026-07-23 *nicht* installiert. Der Boot-Patcher ist
darauf **gated**: fehlt das Paket, trägt er die Sensorparameter nicht ein
(move_group läuft dann exakt wie bisher, ohne Fehlerzeile), und sobald das
Paket vorhanden ist, aktiviert sich der Octomap beim nächsten Boot von
selbst. Die Installation ist eine **Admin-Entscheidung im Wartungsfenster**
(apt hat diesen Roboter schon einmal zerlegt — siehe Snapshot/Hold-Historie):
vorher mit `apt-get install -s ros-jazzy-moveit-ros-perception` simulieren
und nur fortfahren, wenn dabei **nichts** aktualisiert oder entfernt wird
(Stand 2026-07-23 stammt der Kandidat `2.12.4-1noble.20260412.063337` aus
demselben Snapshot wie das installierte `moveit-core` — die Simulation
sollte also nur das neue Paket zeigen).

**Verifikation nach Install + Reboot (Checkliste):**

1. `journalctl -u clearpath-custom-octomap-feed -b` → Startzeile mit Topic/Rate.
2. `ros2 topic hz /a200_0553/sensors/camera_0/octomap_points` → ~5 Hz.
3. `journalctl -t clearpath-custom-setup -b | grep octomap` → „Occupancy-Map-
   Monitor eingetragen“ (bzw. „bereits korrekt“).
4. move_group-Log: Zeile „Listening to '…/octomap_points' using message filter
   with target frame 'base_link'“ (Monitor aktiv).
5. RViz (offboard-lite): PlanningScene-Display → Octomap-Voxel sichtbar; Hand
   vor die Kamera halten → Voxel erscheinen, wegnehmen → verschwinden (Raycast).
6. Greif-Regression: Würfel-Collision-Objects dürfen KEINE Voxel tragen
   (Maskierung); ein Descend auf einen Würfel muss weiterhin planen.
7. CPU: `top` auf dem Onboard-PC — Feed + move_group-Insertion zusammen sollten
   im einstelligen Prozentbereich bleiben; sonst `rate_hz`/`stride` senken
   (ROS-Params der Unit) und `max_range` reduzieren.

**Rollback:** `sudo systemctl disable --now clearpath-custom-octomap-feed`,
Unit-Datei löschen, reboot — der Patcher lässt `moveit.yaml` dann unangetastet
(die generierte Datei entsteht ohnehin bei jedem Boot neu; `.bak` liegt daneben).
