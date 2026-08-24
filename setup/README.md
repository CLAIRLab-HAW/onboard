# Husky

Das Custom-Setup des Clearpath a200-0553: ein Installer, der die Boot-Services,
udev-Regeln, das Netz und den OnRobot-RG6 einrichtet, dazu die Knoten, die
Clearpath selbst nicht mitbringt. `robot.yaml` ist dabei die einzige Quelle der
Wahrheit — `/etc/clearpath/robot.yaml` ist ein Symlink auf den Repo-Klon.

## Features

- **`robot.yaml` ist die Single Source of Truth** —
  `/etc/clearpath/robot.yaml` ist ein Symlink auf den Repo-Klon, ein
  `git pull` wirkt also binnen Sekunden statt erst beim nächsten Boot.
- **8 Services + 1 Timer**, alle mit dem Präfix `clearpath-custom-*`.
- **Ein Watchdog für spätes Einschalten des Arms** und für eine Motion-Link,
  die gestorben ist, während ExternalControl weiter „läuft" meldete.
- **`rg6_grip_bridge`** — der Knoten, der den RG6 tatsächlich fährt, per
  XML-RPC gegen die OnRobot-URCap.
- **Manipulator-Diagnose in Cockpit**: Arm-Mode, Control, Gelenke, Controller
  und Greifer als `diagnostic_msgs`, mit einem ausdrücklichen Zustand
  *außer Betrieb* statt erfundener Zahlen.
- **Ein Boot-Patcher mit drei Schritten** — alles, was `robot.yaml`
  ausdrücken kann, ist dorthin gewandert.

## Tech Stack

Ubuntu + ROS 2 Jazzy auf dem Clearpath a200-0553, systemd, `rclpy`,
`ur_robot_driver`, Zenoh (`rmw_zenoh_cpp`). Bash-Installer, kein
Konfigurationsmanagement.

## Installation

Nach der Installation des Clearpath-Software-Stacks
([Clearpath Installation](https://docs.clearpathrobotics.com/docs/ros/installation/robot))
im eigenen Nutzerverzeichnis:

```bash
wget -c https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/install-clearpath-custom-setup.sh
bash -e install-clearpath-custom-setup.sh
```

Der Installer ist interaktiv und fragt vor jedem optionalen Teil (`[y/N]`,
oder `-y`, um alles zu bejahen). `--verify` prüft rein lesend, ob die
ausgerollten Kopien noch dem Checkout entsprechen, und ändert nichts.

Alle Units, die der Installer anlegt, tragen das Präfix `clearpath-custom-*`
(`clearpath-custom-rg6-grip-bridge`, `clearpath-custom-joint-states`,
`clearpath-custom-ur-dashboard`, `clearpath-custom-ur-state-manager`,
`clearpath-custom-manipulator-diagnostics`, `clearpath-custom-octomap-feed`,
`clearpath-custom-manipulators-watchdog.service`/`.timer` und
`clearpath-custom-setup`). Die Arm-Controller sind kein eigener Service,
sondern Teil von `ur_state_manager.launch.py` (Argument
`load_arm_controllers`). Drop-ins auf Clearpath-eigenen Units
(`clearpath-manipulators.service.d/override.conf`) behalten nach
systemd-Konvention den Namen ihrer Ziel-Unit.

## Usage

Was die installierten Units tun, je ein Abschnitt.

### `clearpath-custom-manipulators-watchdog.timer` (spätes Einschalten)

Der Watchdog deckt zwei Fälle ab, die aus einem ROS-Knoten heraus nicht zu
beheben sind — beide brauchen die tote Treiber-Verbindung für ihre eigenen
Eingaben und können den Treiber-Prozess, von dem sie abhängen, nicht neu
starten. Der Installer bietet deshalb einen kleinen **systemd-Timer** an:

**(a) Später eingeschalteter Arm.** Wird der UR5 erst **lange nach** dem Boot
des ROS-Stacks bestromt, ist die einmalige ros2_control-Hardware-Aktivierung
des `ur_robot_driver` schon gegen den damals stromlosen Arm gescheitert — und
ros2_control wiederholt sie **nicht**. Der Treiber steht mit einer toten
Hardware-Komponente da, das Panel bleibt auf **„Stopped"**.

**(b) Hängender Reconnect nach einem `clearpath-robot.service`-Restart bei
schon bestromtem Arm.** Die alte `ExternalControl`-Instanz hält das
Reverse-Socket; die Hardware-Aktivierung des neuen Treibers scheitert an der
Socket-Kollision → `joint_state_broadcaster` bleibt inaktiv → RViz und
MoveIt fallen auf die URDF-Default-Pose zurück, der Arm liegt **flach**.

Das Health-Signal ist **der `joint_state_broadcaster`-Strom**
(`/a200_0553/manipulators/joint_states`): er publiziert echte Arm-Gelenke
**nur**, wenn das ros2_control-Hardware-Interface aktiviert ist.
`robot_program_running` allein ist **kein** gültiges Health-Signal — das ist
der controller-seitige ExternalControl-Status (über Dashboard/RTDE gelesen)
und bleibt `true`, auch wenn die PC-seitige Motion-Link tot ist. Genau das ist
Fall (b).

Alle 10 s (ab `OnBootSec=90`) prüft er: **Arm pingbar** (`192.168.131.40`),
**aber JSC-Strom stumm** → ist der Arm **nicht** `POWER_OFF`, läuft
`systemctl restart clearpath-manipulators.service` **einmal** (mit Cooldown,
Zustand in `/run`, damit es nicht schleifen kann) und danach ein Neustart von
`ExternalControl` (`resend_robot_program`). Er bestromt den Arm **nicht**
(kein `power_on`/`brake_release`) — Bestromen ist eine Bedienerentscheidung
und schützt Wartung und Feierabend; steht der Arm auf `POWER_OFF`, läuft
keine Recovery, damit kein Treiber-Neustart gegen einen stromlosen Arm
schleift.
Sobald der Bediener bestromt, verbindet der Watchdog die Motion-Link beim
nächsten Takt. Protective- und Safety-Stops (`safety_mode != NORMAL`) werden
**nicht** automatisch aufgehoben — der `resend` entfällt, das Freigeben
bleibt manuell.

Ein großzügiges Grace-Fenster (`JS_TIMEOUT`, 25 s) verhindert Fehlalarme
während der rund 15 s, die der JSC nach einem Neustart braucht; auf einem
gesunden Boot (JSC streamt) und bei ausgeschaltetem Arm (nicht pingbar) bleibt
der Watchdog still. Der **Greifer** ist davon nicht berührt: er hängt an der
OnRobot-URCap, und kein ROS-Service kann seinen Tool-Anschluss bestromen —
siehe den Greifer-Abschnitt weiter unten. Logs:
`journalctl -t manipulators-watchdog -b`; Zeitplan:
`systemctl list-timers clearpath-custom-manipulators-watchdog.timer`.

### `clearpath-manipulators.service.d/override.conf` (sauberer Stopp)

Ein Drop-in, das `clearpath-manipulators.service` mit `KillSignal=SIGINT`
statt des voreingestellten `SIGTERM` stoppen lässt. `ros2_control_node`,
`move_group` und `robot_state_pub` sind ROS-Knoten und behandeln `SIGINT` als
Graceful Shutdown (Reverse- und Dashboard-Sockets in rund 1–3 s geschlossen);
unter `SIGTERM` ignoriert der alte `ros2_control_node` das Signal und hängt
bis zu 90 s als Zombie herum, der das Reverse-Socket weiter hält — genau das
verursacht die Socket-Kollision in Fall (b) oben. Das Drop-in layert über der
Clearpath-eigenen Unit und überlebt Paket-Updates.

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
   | Arm `POWER_OFF` | **außer Betrieb** (grau): `arm switched off - gripper without supply` |
   | Arm bestromt, kein Signal | **WARNUNG**: `tool unpowered: is the URCap program running on the pendant?` |
   | Arm sonst unbestromt (z. B. `BOOTING`) | **WARNUNG**: `arm not powered` |

   und Weite/Prozent/`grip_detected`/`busy` stehen dann auf `unknown` statt
   auf erfundenen Zahlen; die Rohspannungen bleiben sichtbar (sie *sind* die
   Diagnose).

   Dieselbe Logik gilt für den Arm selbst: `POWER_OFF` ist eine
   Bedienerentscheidung (Wartung/Feierabend), kein Fehler — `Arm Mode`,
   `Arm Control`, `Arm Joints` und der Gutfall von `Arm Controllers` melden
   dann **außer Betrieb** statt gelb/rot. Der Watchdog verhält sich genauso
   (bei `POWER_OFF` läuft keine Recovery). Ein echtes Problem schlägt das
   weiterhin durch: ein Safety-Stopp bleibt auch am ausgeschalteten Arm ROT
   (live verifiziert an einem `FAULT` nach Power-Cycle), ein fehlender
   Controller ebenfalls. Am unbestromten Arm rauscht die
   Gelenkgeschwindigkeit bis 0,055 rad/s (bestromt: exakt 0,0000) — `moving`
   steht deshalb auf `unknown`, solange der Arm aus ist, und die Schwelle
   liegt bei 0,02 rad/s (`motion_eps_rad_s`).

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

   Der Block steht bedingungslos in `robot.yaml`, an keine Unit-Datei
   gekoppelt. Ohne den Diagnose-Node zeigt Cockpit die Gruppe darum als STALE,
   statt sie verschwinden zu lassen. Rückbau = Block aus `robot.yaml`
   entfernen.

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
   verschwindet, `grip_detected`/`busy`/`moving` stehen auf `unknown`.
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

Drei der Python-Knoten tragen einen ROS-freien Selbsttest:

```bash
python3 scripts/manipulator_diagnostics.py --selftest
python3 scripts/rg6_grip_bridge.py --selftest
python3 scripts/octomap_feed.py --selftest
```

Der Installer fährt denselben Selbsttest, bevor er eine Datei ausrollt, und
verwirft eine Quelle, die sich nicht einmal übersetzen lässt.
`bash install-clearpath-custom-setup.sh --verify` vergleicht rein lesend die
ausgerollten Kopien mit dem Checkout.

## Related

- [onrobot-rg6](../onrobot-rg6/README.md) — Greifermodell, MoveIt-Patch,
  Container-Mock
- [ur-state-manager](../ur-state-manager/README.md) — Armzustand und
  Controller-Modi
- [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md) — das
  Panel, das diese Diagnose darstellt

## Versioning

[Semantic Versioning](https://semver.org/) über die Datei `VERSION` und
[CHANGELOG.md](CHANGELOG.md).

## License

Siehe Workspace-Wurzel.
