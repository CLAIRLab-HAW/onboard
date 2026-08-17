# Changelog — husky-custom-setup

Was sich wann geändert hat. Der aktuelle Stand steht in der [README](README.md).

## 2026-08-17

- Der Greifer wird per **XML-RPC** kommandiert, nicht mehr über Tool-DO0.
  `scripts/rg6_grip_bridge.py` nimmt `/twin/gripper_cmd` an und ruft
  `rg_grip(tool, width, force)` auf `http://192.168.131.40:41414/`; der neue
  Dienst heisst `clearpath-custom-rg6-grip-bridge`. Der bisherige Weg über
  `rg6_control` ist seit dem RTDE-Recipe-Split (`31a45d0`) tot und nicht
  kaputt: die OnRobot-URCap ist selbst RTDE-Client und belegt
  `tool_digital_output_mask`, der Treiber läuft deshalb auf einem Recipe ohne
  diese Zeilen — und `rg6_control` steuerte den Greifer ausschliesslich
  darüber. Am 2026-08-17 gemessen: Unit `inactive (dead)`,
  `/…/rg6/state` ohne Publisher.
- Der Node läuft **onboard**, nicht im Offboard-Container. Der Endpoint hängt
  am Arm-Subnetz `192.168.131.0/24`, zu dem es von der Workstation keine Route
  gibt (gemessen: TCP-Timeout; netbird annonciert das Subnetz nicht) — und der
  Roboter muss greifen können, auch wenn die Funkstrecke weg ist.
- `rg6_finger_joint` steht wieder in den `joint_states`. Seit `rg6-bringup`
  tot ist, fehlte er: move_group sah den Greifer in seiner Default-Stellung,
  und **jede Freiraumprüfung um die Hand rechnete gegen eine Stellung, die
  er nicht hat.** Der Node leitet ihn aus der gemessenen Weite ab, über die
  Getriebegeometrie des Profils.
- Der Status kommt vom Gerät statt aus einer Spannungsnäherung. Der Endpoint
  bietet `rg_get_width`, `rg_get_busy`, `rg_get_grip_detected`,
  `rg_get_status` und `rg_get_safety_failed` — die frühere Notiz, es gebe
  über XML-RPC keinen Status, war falsch. Damit ist `grasped` echt
  dreiwertig statt aus `stalled`/`reached_goal` erschlossen.
- Der Installer legt jetzt auch `rtde_input_recipe_no_tool.txt` nach
  `/home/robot/` ab. `robot.yaml` zeigt fest dorthin; fehlte die Datei nach
  einem Neuaufsetzen, startete der UR-Treiber nicht — ohne jeden Hinweis auf
  sie. Ebenso wird `robot_contract` mit ausgerollt (nach
  `/usr/local/lib/spact`), damit der Draht-Vertrag nicht als Zweitfassung im
  Node nachgebaut werden muss.
- `scripts/rg6_kennlinie.py` fährt den ganzen Greiferweg ab und notiert je
  Stützstelle die Geräteweite. Damit bekommt die bis heute **geratene**
  AI2-Kennlinie (`in_closed = 0,56 V`, `in_open = 10,0 V`) erstmals eine
  Referenz: an einem Punkt gemessen liegt sie um **16,6 mm** daneben
  (AI2 5,6696 V, Gerät 103,26 mm, Kennlinie 86,6 mm). Das Skript **bewegt den
  Greifer** und gehört an einen Termin mit jemandem am Gerät.
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
