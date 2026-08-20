# Husky
After installing the clearpath software stack (see [Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot)), run this line in your user directory:

``
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh && bash -e install-clearpath-custom-setup.sh
``

The installer is interactive and asks (each step `[j/N]`, or pass `-y` to accept all) before optional parts. One of them installs **`clearpath-custom-ur-dashboard.service`** — it starts the `ur_robot_driver` `dashboard_client` on boot (`power_on`/`brake_release`/`unlock_protective_stop`/`restart_safety`/`get_robot_mode`/`get_safety_mode`), which Clearpath does *not* bring up in the headless setup. The services land under `/a200_0553/manipulators/dashboard_client/*` and are consumed by the `ur_state_manager` package (repo [`ur-state-manager`](https://github.com/CLAIRLab-HAW/ur-state-manager)), which the installer can also clone, build and start on boot (`clearpath-custom-ur-state-manager.service`).

All custom units the installer creates carry the `clearpath-custom-*` prefix (`clearpath-custom-rg6-bringup`, `clearpath-custom-joint-states`, `clearpath-custom-ur-dashboard`, `clearpath-custom-ur-state-manager`, `clearpath-custom-manipulator-diagnostics`, `clearpath-custom-octomap-feed`, `clearpath-custom-manipulators-watchdog.service`/`.timer`, plus `clearpath-custom-setup`) — **8 Services + 1 Timer**. Die Arm-Controller sind kein eigener Service, sondern Teil von `ur_state_manager.launch.py` (Argument `load_arm_controllers`). Ein Installer-Lauf räumt Alt-Units aus früheren Setups automatisch weg: `clearpath-custom-arm-controllers`, `clearpath-custom-robot-yaml-update` und die alten, unpräfigierten Namen werden disabled und entfernt (Migrationsfenster: diese Services stoppen kurz, dann starten die umbenannten). Drop-ins on Clearpath-owned units (`clearpath-manipulators.service.d/override.conf`) keep their target-unit name by systemd convention.

**`/etc/clearpath/robot.yaml` ist ein Symlink** auf den Repo-Klon `~/husky-custom-setup/robot.yaml` — der offizielle Clearpath-Weg, kein eigener Update-Service. `clearpath-robot-check` md5summt die Datei im Sekundentakt, ein `git pull` wirkt also sofort statt erst beim nächsten Boot.

## Features

- **`robot.yaml` is the single source of truth** — `/etc/clearpath/robot.yaml`
  is a symlink onto the repo clone, so a `git pull` takes effect within seconds
  instead of at the next boot.
- **8 services + 1 timer**, all prefixed `clearpath-custom-*`; an installer run
  also removes units from older setups.
- **A watchdog for late arm power-on** and for a motion link that died while
  ExternalControl kept claiming to run.
- **`rg6_grip_bridge`** — the node that actually drives the RG6, over XML-RPC
  against the OnRobot URCap.
- **Manipulator diagnostics in Cockpit**: arm mode, control, joints,
  controllers and gripper as `diagnostic_msgs`, with an explicit
  *out-of-service* state rather than invented numbers.
- **A boot patcher down to two steps** — everything that `robot.yaml` can
  express has moved there, and the sensor mesh URIs are fixed upstream.

## Tech Stack

Ubuntu + ROS 2 Jazzy on the Clearpath a200-0553, systemd, `rclpy`,
`ur_robot_driver`, Zenoh (`rmw_zenoh_cpp`). Bash installer, no configuration
management.

## Installation

After installing the Clearpath software stack
([Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot)),
run this in your user directory:

```bash
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh
bash -e install-clearpath-custom-setup.sh
```

The installer is interactive and asks before each optional part (`[j/N]`, or
`-y` to accept all).

## Usage

Was die installierten Units tun, je ein Abschnitt.

### `clearpath-custom-manipulators-watchdog.timer` (late arm power-on + stuck reconnect after restart)

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
`ur_state_manager`'s `auto_recover` brings the arm's motion link back once the arm is
powered and the program runs. The **gripper** is not part of that: it hangs off the
OnRobot URCap, and no ROS service can power its tool connector — see the gripper section
below. A generous `JS_TIMEOUT` (25 s) grace window prevents false alarms during the ~15 s
the JSC needs to come up after a restart; it stays silent on a healthy boot (JSC
streaming) and while the arm is off (not pingable). Logs:
`journalctl -t manipulators-watchdog -b`; schedule:
`systemctl list-timers clearpath-custom-manipulators-watchdog.timer`.

### `clearpath-manipulators.service.d/override.conf` (clean driver shutdown)

A drop-in that makes `clearpath-manipulators.service` stop with `KillSignal=SIGINT`
instead of the default `SIGTERM`. `ros2_control_node` / `move_group` / `robot_state_pub`
are ROS nodes and handle `SIGINT` as graceful shutdown (reverse/dashboard sockets closed
in ~1–3 s); under `SIGTERM` the old `ros2_control_node` ignores the signal and lingers up
to 90 s as a zombie still holding the reverse socket — which is what causes the socket
collision in case (b) above. The drop-in layers over the Clearpath-owned unit and
survives package updates.

### `clearpath-custom-manipulator-diagnostics.service` (UR5 + RG6 in Cockpit)

Cockpit zeigt über die Erweiterung
[`cockpit-ros2-diagnostics`](https://github.com/clearpathrobotics/cockpit-ros2-diagnostics)
den Inhalt von `<ns>/diagnostics_agg`. **Der Manipulator fehlt dort komplett** —
und zwar an drei Stellen gleichzeitig:

* `clearpath_generator_common` erzeugt Analyzer nur für Platform (Power, E-Stop,
  Drive) und Sensoren; Arm/Greifer kommen im Generator gar nicht vor.
* Der `controller_manager` des Arms publiziert seine Diagnose in den
  *manipulators*-Namespace (`/a200_0553/manipulators/diagnostics`) — nicht auf
  `/a200_0553/diagnostics`, das der Aggregator abonniert.
* `ur_robot_driver` liefert seinen Zustand als `ur_dashboard_msgs`, der Greifer als
  flaches JSON auf `rg6/bridge_state` — beides nicht als `diagnostic_msgs`.

Drei Bausteine schließen die Lücke, alle vom Installer (optionale Schritte):

1. **`manipulator-diagnostics`** (`scripts/manipulator_diagnostics.py`,
   root-eigene Kopie unter `/usr/local/bin`): publiziert mit 1 Hz fünf Status auf
   `/a200_0553/diagnostics`. Ein `onrobot-rg6`-Overlay braucht der Wrapper nicht —
   der Greiferzustand kommt als JSON, nicht als `rg6_msgs`-Typ:

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

   **Der Armzustand entscheidet über den Greifer.** Der RG6 hängt
   am UR-Tool-Anschluss — ohne bestromten Arm kann er gar keine Versorgung
   haben. Der Zustand, den `rg6_grip_bridge` auf `rg6/bridge_state` meldet,
   taugt als Nachweis dafür *nicht*: die Brücke fragt den XML-RPC-Endpoint in
   der Control-Box, und der antwortet auch dann, wenn am Tool-Anschluss nichts
   anliegt — er weiß, was er zuletzt kommandiert hat, nicht was die Hardware
   tut.

   Maßgeblich ist deshalb weiterhin die **Tool-Spannung**: Analogsignal unter
   `dead_input_threshold` (0,2 V) = kein gültiges Tool-Signal. Gemessen am
   a200-0553: bestromt AI2 10,00 V / AI3 1,33 V, stromlos beide ~0,056 V. Als
   *Weitenquelle* taugt AI2 nicht (bis zu 17 mm falsch geeicht) — die Frage,
   die es beantwortet, ist allein „liegt am Tool-Anschluss Versorgung an".
   Ist das Signal ungültig, meldet der Status je nach Ursache

   | Lage | Meldung |
   |---|---|
   | Arm `POWER_OFF` | **außer Betrieb** (grau): „Arm ausgeschaltet – Greifer ohne Versorgung" |
   | Arm bestromt, kein Signal | **WARNUNG**: „Tool stromlos — läuft das URCap-Programm auf dem Panel?" |
   | Arm sonst unbestromt (z. B. `BOOTING`) | **WARNUNG**: „Arm nicht bestromt" |

   und Weite/Prozent/`grip_detected`/`busy` stehen dann auf `unbekannt` statt
   auf erfundenen Zahlen; die Rohspannungen bleiben sichtbar (sie *sind* die
   Diagnose).

   Dieselbe Logik gilt für den Arm selbst: `POWER_OFF` ist eine
   Bedienerentscheidung (Wartung/Feierabend), kein Fehler — `Arm Mode`,
   `Arm Control`, `Arm Joints` und der Gutfall von `Arm Controllers` melden
   dann **außer Betrieb** statt gelb/rot. Der Watchdog verhält sich genauso
   (bei `POWER_OFF` läuft keine Recovery). Ein echtes Problem schlägt das
   weiterhin durch: ein Safety-Stopp bleibt auch am ausgeschalteten Arm ROT
   (live verifiziert an einem `FAULT` nach Power-Cycle), ein fehlender
   Controller ebenfalls. Nebenbei behoben: `Arm Joints` meldete am
   unbestromten Arm „in Bewegung", weil die Gelenkgeschwindigkeit dort bis
   0,055 rad/s rauscht (bestromt: exakt 0,0000) — `moving` ist jetzt
   `unbekannt`, solange der Arm aus ist, und die Schwelle liegt bei
   0,02 rad/s (`motion_eps_rad_s`).

   **Kodierung von „außer Betrieb":** `diagnostic_msgs` kennt nur
   OK/WARN/ERROR/STALE. Ein eigener Byte-Wert würde die `max()`-Rollups des
   Aggregators und jeden Fremdkonsumenten (`rqt_robot_monitor`, Capture)
   verwirren. Der Status bleibt daher **OK** (es ist ja nichts kaputt) und
   trägt zusätzlich den Wert `display=inactive`; nur Cockpit färbt daraus grau.

2. **`robot.yaml`** unter `platform.extras.ros_parameters.diagnostic_aggregator`:
   eine AnalyzerGroup `Manipulator` mit den Untergruppen `Arm` und `Gripper`.
   Der Clearpath-Generator merged sie in die erzeugte
   `/etc/clearpath/platform/config/diagnostic_aggregator.yaml` und flacht die
   Verschachtelung selbst auf die Punkt-Keys ab, die ROS erwartet; die 20
   Upstream-`platform.analyzers.*` und die Sensor-Analyzer bleiben unangetastet.
   Die Analyzer listen ihre Status als `expected`: stirbt der Node, bleiben sie
   als **STALE** in der Anzeige stehen statt spurlos zu verschwinden.

   Bis zum 2026-08-19 stand das im Boot-Patcher (Schritt 6) und lief **nur**,
   wenn die Unit-Datei existierte — die Datei war der Feature-Schalter. Diese
   Kopplung gibt es nicht mehr: der Block steht bedingungslos in `robot.yaml`.
   Ohne den Diagnose-Node zeigt Cockpit die Gruppe darum als STALE, statt sie
   verschwinden zu lassen. Rückbau = Block aus `robot.yaml` entfernen.

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

   Der Fork ist außerdem **auf Deutsch übersetzt** (`po/de.po`; Cockpit lädt
   `po.<lang>.js` passend zur Spracheinstellung, inklusive des Menüeintrags)
   und stuft zwei Fremdmeldungen herunter, die den ganzen Roboter dauerhaft
   rot färbten: `joy_node: Joystick Driver Status` „Joystick not open." →
   **inaktiv** (kein Gamepad angesteckt ist der Normalzustand) und
   `controller_manager: Hardware Components Activity` „High execution jitter"
   → **Warnung** (systembedingt bei der seriellen 10-Hz-Anbindung der Basis).
   Die Regeln stehen in `src/utils/severity.ts`, greifen nur bei passendem
   Namen **und** passender Meldung, und das Detail-Panel zeigt weiterhin die
   ursprünglich gemeldete Stufe samt Begründung. Sauberer wäre für den Jitter
   `diagnostics.threshold.hardware_components.*` am `controller_manager` —
   das schaltet die Meldung aber ganz ab, statt sie herabzustufen.

   Installiert wird nach `/usr/local/share/cockpit/ros2-diagnostics`. Cockpit
   sucht in der Reihenfolge `~/.local/share/cockpit`, `/etc/cockpit`,
   `/usr/local/share/cockpit`, `/usr/share/cockpit` — der Fork **überdeckt**
   damit das apt-Paket, ohne es zu ersetzen. Rückbau: Verzeichnis löschen, das
   Original ist sofort wieder aktiv (kein apt nötig). Umgekehrt gilt: solange
   der Fork liegt, sind apt-Updates von `cockpit-ros2-diagnostics` nicht
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
2. `grep -A2 "manipulator.type" /etc/clearpath/platform/config/diagnostic_aggregator.yaml`
   → `diagnostic_aggregator/AnalyzerGroup` (der Generator hat den robot.yaml-Block
   übernommen; im Journal des Patchers steht dazu nichts mehr).
3. `ros2 topic echo /a200_0553/diagnostics_agg --once` → Einträge unter
   `/Clearpath Diagnostics/Manipulator/Arm/…` und `…/Gripper`.
4. Cockpit (`http://<robot>:9090` → ROS 2 Diagnostics): Karte **Manipulator**
   mit Arm- und Greifer-Kachel.
5. Funktionsprobe: Greifer öffnen/schließen → Balken + `grip_detected` folgen.
6. Abschaltprobe (`ur_state_manager/power_off`): Manipulator-Kachel, Arm- und
   Greifer-Kachel werden **grau/„Außer Betrieb"**, der Öffnungsbalken
   verschwindet, `grip_detected`/`busy`/`moving` stehen auf `unbekannt`.
   Danach `prepare` und das URCap-Programm am Panel starten → wieder alles grün.
   (Die Tool-Versorgung setzt die OnRobot-URCap, nicht ROS: der Weg dorthin ging
   über Tool-DO, und den belegt die URCap selbst. Kein ROS-Service kann das hier
   reparieren; solange meldet der Status WARNUNG mit genau diesem Hinweis.)
7. Rückbau-Probe: `systemctl disable --now
   clearpath-custom-manipulator-diagnostics` → die Analyzer **bleiben** in der
   generierten YAML und die Gruppe steht als **STALE** in `diagnostics_agg`;
   das Panel rendert dann nichts mehr. Sollen auch die Analyzer weg, den Block
   aus `robot.yaml` entfernen (wirkt über `clearpath-robot-check` sofort).

### `clearpath-custom-octomap-feed.service` (MoveIt-Octomap: dichte Hindernis-Schicht)

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
2. **Sensor-Parameter in `robot.yaml`**: unter
   `manipulators.moveit.ros_parameters.move_group`
   stehen `octomap_frame`, `octomap_resolution`, `sensors` und der
   `wrist_depth_camera`-Block — der Clearpath-Generator schreibt sie selbst in
   `/etc/clearpath/manipulators/config/moveit.yaml`. `octomap_frame` ist bewusst
   `base_link` (odom ist auf diesem Roboter UTM-gestützt und springt),
   `octomap_resolution` 0.025, `max_range` 2.0.
   **Achtung:** es gibt kein Gate „nur wenn `moveit_ros_perception` installiert
   ist". Fehlt das Paket, quittiert `move_group` das mit einem
   Plugin-Load-Fehler pro Boot. Auf a200-0553 ist es installiert.

**Zusammenspiel mit den Objekt-Collision-Objects:** MoveIts
PlanningSceneMonitor maskiert bekannte World-Objects und attachte Bodies aus
dem Octree (`excludeWorldObjectsFromOctree` / `excludeAttachedBodiesFromOctree`)
— die von der Workstation gepushten Würfel, der Boden-Slab und die Hindernis-Boxen erzeugen
also keine blockierenden Voxel; Griffe bleiben planbar. Der Roboter selbst wird
vom Updater geometrisch selbst-gefiltert (`padding_offset` 0.03).

**Voraussetzung (bewusst NICHT vom Installer erledigt):** der
`PointCloudOctomapUpdater` kommt aus **`ros-jazzy-moveit-ros-perception`**.
Weil die Sensorparameter in `robot.yaml` stehen, gibt es kein
Boot-Patcher-Gate: `move_group` lädt die Sensor-Blocke aus der
generierten `moveit.yaml` **immer**, und fehlt das Paket, quittiert es das
mit einem Plugin-Load-Fehler pro Boot (s.o.). Die Installation ist eine
**Admin-Entscheidung im Wartungsfenster**
(apt hat diesen Roboter schon einmal zerlegt — siehe Snapshot/Hold-Historie):
vorher mit `apt-get install -s ros-jazzy-moveit-ros-perception` simulieren
und nur fortfahren, wenn dabei **nichts** aktualisiert oder entfernt wird
(der Kandidat `2.12.4-1noble.20260412.063337` stammt aus demselben Snapshot
wie das installierte `moveit-core` — die Simulation sollte also nur das neue
Paket zeigen).

**Verifikation nach Install + Reboot (Checkliste):**

1. `journalctl -u clearpath-custom-octomap-feed -b` → Startzeile mit Topic/Rate.
2. `ros2 topic hz /a200_0553/sensors/camera_0/octomap_points` → ~5 Hz.
3. `grep -A10 wrist_depth_camera /etc/clearpath/manipulators/config/moveit.yaml`
   → der Sensor-Block steht in der generierten Datei (kommt aus robot.yaml).
4. move_group-Log: Zeile „Listening to '…/octomap_points' using message filter
   with target frame 'base_link'“ (Monitor aktiv).
5. RViz (offboard-lite): PlanningScene-Display → Octomap-Voxel sichtbar; Hand
   vor die Kamera halten → Voxel erscheinen, wegnehmen → verschwinden (Raycast).
6. Greif-Regression: Würfel-Collision-Objects dürfen KEINE Voxel tragen
   (Maskierung); ein Descend auf einen Würfel muss weiterhin planen.
7. CPU: `top` auf dem Onboard-PC — Feed + move_group-Insertion zusammen sollten
   im einstelligen Prozentbereich bleiben; sonst `rate_hz`/`stride` senken
   (ROS-Params der Unit) und `max_range` reduzieren.

**Rollback:** `sudo systemctl disable --now clearpath-custom-octomap-feed` **und**
den `move_group`-Block aus `robot.yaml` entfernen (sonst sucht der Updater weiter
eine Wolke, die niemand publiziert). Die Änderung an robot.yaml wirkt sofort —
`clearpath-robot-check` startet den Stack neu; die generierte Datei entsteht
ohnehin bei jedem Boot neu, ein `.bak` liegt daneben.

## Running Tests

Both Python nodes carry a ROS-free self-test:

```bash
python3 scripts/manipulator_diagnostics.py --selftest
python3 scripts/rg6_grip_bridge.py --selftest
```

## Related

- [onrobot-rg6](../onrobot-rg6/README.md) — gripper model, MoveIt patch,
  container mock
- [ur-state-manager](../ur-state-manager/README.md) — arm state and controller
  modes
- [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md) — the panel
  that renders these diagnostics

## Versioning

[Semantic Versioning](https://semver.org/) via the `VERSION` file and
[CHANGELOG.md](CHANGELOG.md).

## License

See workspace root.
