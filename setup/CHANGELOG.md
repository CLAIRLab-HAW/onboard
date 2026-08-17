# Changelog — husky-custom-setup

Was sich wann geändert hat. Der aktuelle Stand steht in der [README](README.md).

## 2026-08-17

- `clearpath-custom-rg6-bringup.service` gibt jetzt auf, statt endlos neu zu
  starten: `StartLimitIntervalSec=120` und `StartLimitBurst=5` im
  `[Unit]`-Block. Vorher griff systemds Voreinstellung **nie** — am Roboter
  nachgemessen: `StartLimitIntervalUSec=10s`, `StartLimitBurst=5`, aber
  `RestartSec=5`. In ein 10-Sekunden-Fenster passen bei 5 s Abstand nur zwei
  Neustarts, die Grenze von fünf wurde also nicht erreicht, und ein
  fehlgeschlagener `colcon`-Build erzeugte eine endlose Fünf-Sekunden-Schleife,
  die Logs flutete und CPU zog, ohne je grün zu werden. Fünf Versuche dauern
  jetzt rund 25 s, danach bleibt die Unit als `failed` sichtbar stehen, statt
  sich selbst zu verdecken.
- Die Umbenennung vom 2026-08-13 ist am a200-0553 **ausgerollt**: `~/wakeup.sh`
  und `~/shutdown.sh` sind Symlinks auf `scripts/` (keine Kopien mehr — genau
  die Konstruktion, aus der der `octomap_feed.py`-Drift entstand),
  `~/guten-morgen.sh` und `~/feierabend.sh` sind entfernt.

## 2026-08-13

- Die Tagesskripte heissen englisch: `guten-morgen.sh` → `wakeup.sh`,
  `feierabend.sh` → `shutdown.sh`. Auf dem provisionierten a200-0553 sind noch
  die alten Namen ausgerollt (`~/guten-morgen.sh`, `~/feierabend.sh` bzw. das
  Checkout unter `~/husky-custom-setup`) — dort muss der Name einmal
  nachgezogen werden. *(Am 2026-08-17 nachgezogen, s. o.)*

## 2026-07-29

Am Roboter umgesetzt und Reboot-getestet.

- `clearpath-custom-arm-controllers` entfallen — die Arm-Controller sind jetzt
  Teil von `ur_state_manager.launch.py` (Argument `load_arm_controllers`, s.
  [ur-state-manager](../ur-state-manager/CHANGELOG.md)).
- `clearpath-custom-robot-yaml-update` entfallen — ersetzt durch den offiziellen
  Clearpath-Weg: `/etc/clearpath/robot.yaml` ist ein Symlink auf den Repo-Klon
  `~/husky-custom-setup/robot.yaml`. `clearpath-robot-check` md5summt die Datei
  im Sekundentakt, ein `git pull` wirkt also sofort statt erst beim nächsten
  Boot. Ein Installer-Lauf entfernt beide Alt-Units automatisch.
- Die Sensor-Parameter (`octomap_frame`, `octomap_resolution`, `sensors`,
  `wrist_depth_camera`) stehen in `robot.yaml` statt im Boot-Patcher (dessen
  Schritt 5 entfiel). Damit entfällt auch das Gate „nur wenn
  `moveit_ros_perception` installiert ist" — fehlt das Paket, quittiert
  `move_group` das mit einem Plugin-Load-Fehler pro Boot.
- Befund zum Greifer-Status: die Flags aus `rg6_msgs/GripperState` taugen nicht
  als Nachweis für einen bestromten Arm (Latches bzw. kommandierter Sollwert
  statt Hardware-Feedback). Am ausgeschalteten Arm meldete der Greifer deshalb
  „OK, in Bewegung, 0 mm".
- Watchdog-Health-Signal gehärtet: es prüft „Arm-Gelenke kommen an" jetzt auf
  **beiden** Bussen (`manipulators/joint_states` oder `platform/joint_states` mit
  `arm_0_*`) statt allein am Stock-Patch `move_arm_joint_states` zu hängen — ein
  apt-Update hätte dessen Regex brechen und den Watchdog einen kerngesunden
  Roboter dauerhaft neu starten lassen können. Zusätzlich `WD_DRY_RUN=1` zum
  gefahrlosen Testen.
- `ur-dashboard` vom Treiber entkoppelt: der Watchdog riss mit seinem eigenen
  `systemctl restart clearpath-manipulators` genau die Dashboard-Services mit
  runter, die er für `get_robot_mode`/`get_safety_mode`/`resend_robot_program`
  braucht.
- Echtzeit-Scheduling für den manipulators-`controller_manager`: `LimitRTPRIO=99`
  im Drop-in `clearpath-manipulators.service.d/override.conf`. Vorher scheiterte
  `configure_sched_fifo()` mit EPERM, der Loop lief `SCHED_OTHER` und hatte bei
  125 Hz echte Overruns (bis 18,5 ms); danach FIFO/Prio 50 und über vier
  Trajektorien null Overruns. (`/etc/security/limits.conf` greift für
  systemd-Units nicht — der Hebel ist die Unit.)

## 2026-07-23

- `ros-jazzy-moveit-ros-perception` auf a200-0553 installiert (Voraussetzung
  für den `PointCloudOctomapUpdater`).
