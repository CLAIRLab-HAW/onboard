# Changelog — husky-custom-setup

Was sich wann geändert hat. Der aktuelle Stand steht in der [README](README.md).

## 2026-08-19

- **Der Roboter braucht `robot_contract` nicht mehr.** Die Greiferbrücke
  importierte den Vertrag für zehn Dinge; der Installer rollte ihn dafür nach
  `/usr/local/lib/spact` aus. Das Paket ist **privat** — vom Roboter aus nicht
  einmal klonbar (`could not read Username for 'https://github.com'`) —, und
  der Installer hat die Brücke deshalb kommentarlos übersprungen. Eine
  Abhängigkeit, die das Ausrollen verhindert, sichert nichts.
  Aufgeteilt statt verschoben:

  | | wo jetzt |
  |---|---|
  | XML-RPC an die URCap, Fingergelenk, `GripperCommand`-Action | onboard, dieser Node |
  | `/twin/gripper_cmd` + `/twin/result` | `plan_server` im Container, der den Vertrag ohnehin führt |

  Der Node spricht damit **nur noch Standard-ROS** (`control_msgs`,
  `sensor_msgs`, `std_msgs`) und importiert ausserhalb der Standardbibliothek
  nichts. Namen und Kraftgrenzen sind ROS-Parameter; die Getriebekinematik
  kommt als **erzeugte Tabelle** (`scripts/rg6_finger_kinematics.json`, 27
  Stützstellen, max. Interpolationsfehler 0,047 mm — unter der
  Fingerpositionsauflösung von 0,1 mm). Erzeugt aus dem generierten URDF von
  `onrobot-rg6/tools/derive_finger_kinematics.py`, nicht von Hand gepflegt.
  Am Gerät belegt: Selbsttest und Node laufen dort, wo `import robot_contract`
  mit `ModuleNotFoundError` scheitert; ein 100-mm-Ziel über die Action ging
  durch (`SUCCEEDED`, `reached_goal: true`).
- **Der Installer findet seine Dateien jetzt auch standalone.** `install(1)`
  bekam Quelle == Ziel und brach ab; mit `set -e` starb der ganze Lauf, vier
  Zeilen vor dem Block der Greiferbrücke. Neu: `repo_file` sucht neben dem
  Skript, dann im Klon, den der Installer für die `robot.yaml` ohnehin pflegt,
  und erst danach auf GitHub — lokal vor dem Netz (R6), und **nie** mit
  Abbruch. Quelle == Ziel heisst „nichts zu tun".


- **`rg6_control` ist ausser Dienst.** Die Unit
  `clearpath-custom-rg6-bringup` wird nicht mehr geschrieben, sondern beim
  Installer-Lauf **abgeräumt** (disable, stop, `rm` — samt Wrapper
  `rg6-bringup.sh` und den `.bak`-Handabschaltungen vom 2026-08-17). Nur
  nicht mehr zu schreiben hätte sie auf jedem bestehenden Roboter stehen
  lassen, wo sie beim nächsten Boot gegen einen Treiber startet, der über
  Tool-DO nichts mehr bewirken kann. Der **Workspace** `onrobot-rg6` wird
  weiter gebaut: `rg6_description` trägt das Greifermodell im URDF,
  `rg6_moveit_patch` die SRDF-Anpassung, und `clearpath-custom-joint-states`
  startet das Relay aus `rg6_control`. Weg ist ausschliesslich der laufende
  Treiber-Knoten.
- **Die Manipulator-Diagnose liest den Greifer bei der Brücke.** Sie hing an
  `rg6_msgs/GripperState` auf `<ns>/rg6/state` — ein Topic ohne Publisher,
  seit der Treiber steht; das Cockpit-Panel meldete „kein rg6/state". Jetzt
  liest sie `<ns>/rg6/bridge_state` (JSON) und holt AI2/AI3 direkt aus
  `tool_data`. Die beiden Quellen bleiben **getrennt**: der Zustand kommt vom
  Gerät, die Spannung sagt, ob am Tool-Anschluss überhaupt Versorgung
  anliegt. Neu im Panel: `device_status`, `safety_failed` und
  `tool_output_voltage_v` — letzteres ist echtes Hardware-Feedback und
  ersetzt das frühere `tool_power_commanded` (den Treiber-Sollwert). Der
  Diagnose-Wrapper braucht das `onrobot-rg6`-Overlay damit nicht mehr.
- **Die Brücke publiziert ihren Gerätezustand** auf
  `<ns>/rg6/bridge_state` (`std_msgs/String`, JSON, im selben 5-Hz-Poll, der
  schon das Fingergelenk trägt). Kein eigenes Message-Paket: `rg6_msgs` fällt
  mit `rg6_control` aus dem Bootpfad, und ein Statustopf, der ein totes Paket
  braucht, wäre genau die Abhängigkeit, die hier abgebaut wird. Antwortet der
  Endpoint nicht, **schweigt** die Brücke — die Diagnose meldet den Ausfall
  über das Alter des letzten Statuses.
- **Der Greifer ist wieder aus MoveIt kommandierbar — auch auf echter
  Hardware.** Die Brücke bietet jetzt selbst die `control_msgs/GripperCommand`-
  Action an, die `rg6_control` bis zu seinem Ruhestand bediente
  (`…/manipulators/rg6_gripper_controller/gripper_cmd`, Name aus dem Profil).
  Ohne sie zeigte der Controller-Eintrag in `moveit.yaml` auf nichts, und ein
  Greifbefehl aus RViz oder `MoveGroupInterface` lief in einen Timeout statt in
  ein „kann ich nicht". Am Gerät belegt: `ros2 action info` zeigt als Client
  `/a200_0553/moveit_simple_controller_manager` — MoveIts Controller-Manager
  hing die ganze Zeit dort und wartete auf einen Server. Ein Ziel über 80 mm
  ging durch (`SUCCEEDED`, `reached_goal: true`, gefahren auf 83,7 mm
  gemeldet). Im Mock bedient weiterhin `rg6_control_sim` denselben Namen; die
  Brücke läuft nur onboard, es gibt also nie zwei Server.
  **Der Greifer hängt dabei nicht am `controller_manager`** und soll es nicht:
  eine Action läuft im Executor, ein blockierender XML-RPC-Aufruf von 1,3 s im
  8-ms-Zyklus des CB3 wäre das Ende jeder Armregelung. Der Node spinnt deshalb
  mit einem `MultiThreadedExecutor`, damit der Greifbefehl nicht die Zustellung
  von `/twin/gripper_cmd` anhält.
- **Die Erfolgsmeldung der Brücke trug die Weite von *vor* der Fahrt.**
  `rg_grip` quittiert die Annahme, nicht das Ergebnis: `succeeded` kam nach
  0,16 s mit dem Startwert (am Draht gemessen: befohlene 60 mm, gemeldete
  2,8 mm). Betroffen war auch `grasped` — das Feld, wegen dem der Rückweg
  existiert. `await_settled` wartet jetzt auf **beide** `busy`-Flanken; die
  erste ist nötig, weil `busy` nach dem Kommando noch rund 0,4 s auf false
  steht und ein blosses „warte, solange busy" sofort zurückkehrte. Timeouts
  als Parameter (`settle_start_timeout_s`, `settle_motion_timeout_s`,
  `settle_poll_s`), damit ein Kommando ohne Arbeit antwortet statt zu hängen.
- `scripts/rg6_kennlinie.py` stempelt jede Zeile mit `t_read`. Ohne die
  Wanduhr lässt sich eine Stützstelle nicht mit der parallel
  mitgeschriebenen AI2-Spur verknüpfen — und ohne AI2 misst der Durchlauf nur
  sich selbst. Dazu `--settle`, `--force` und `--both`: 2,5 s Ruhe reichen für
  eine Eichung nicht (der gemeldete Wert kriecht danach noch ~0,9 mm weiter),
  und das Handbuch nennt die Sollkraft ausdrücklich als Genauigkeitsbremse.

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
