# Changelog — husky-custom-setup

Was sich wann geändert hat. Der aktuelle Stand steht in der [README](README.md).

Das Format folgt [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung [Semantic Versioning](https://semver.org/lang/de/).

## 2026-08-24 (Prosa auf Englisch, Dateinamen nachgezogen)

Reiner Prosa- und Namenslauf nach den Code-Stil-Regeln der Workspace-
`CLAUDE.md` (Stand 2026-08-24). **Kein Verhalten geändert** — die einzigen
Ausnahmen stehen unten unter „Sichtbar am Gerät".

- **Kommentare und Docstrings sind englisch.** Betroffen sind alle vier
  Python-Skripte, `wakeup.sh`, `shutdown.sh`, der Installer samt dem
  eingebetteten `clearpath-custom-setup.py` und dem Watchdog-Wrapper sowie
  die Kommentare in `robot.yaml`. Die deutsche Prosa bleibt, wo sie hingehört:
  in `README.md` und in dieser Datei.
- **`scripts/rg6_kennlinie.py` heißt jetzt `scripts/rg6_stroke_survey.py`.**
  Der alte Name war der letzte deutsche Dateiname im Repo. Der Bericht
  `docs/superpowers/reports/2026-08-19-rg6-kennlinie.md` und die dazugehörigen
  Rohdaten behalten ihren Namen — sie sind eingefrorenes Protokoll. Der
  Installer rollt das Skript nicht aus, die Umbenennung berührt also nichts
  auf dem Roboter.
- **Deutsche Bezeichner im Code sind fort:** die Schleifenvariablen `eintrag`
  und `kandidat` im Installer heißen `entry` und `candidate`, die Zustände des
  XML-RPC-Doppelgängers im Selbsttest der Brücke `phases`/`idle`/`moving`
  statt `phasen`/`ruht`/`faehrt`.
- **Umlaute stehen wieder ausgeschrieben** statt transliteriert: 90 Stellen in
  dieser Datei, dazu die deutsche Prosa in `robot.yaml`, soweit sie nicht
  ohnehin übersetzt wurde.
- **Grabsteine sind raus.** Kommentare, die erzählten, was früher an einer
  Stelle stand (der stillgelegte `rg6_control`, die abgeschaffte
  `rg6-bringup`-Unit, das Patcher-Gate für die Analyzer), sagen jetzt nur noch
  den Ist-Zustand; die Geschichte steht hier. Ebenso in der README, aus der
  der Absatz „Bis zum 2026-08-19 stand das im Boot-Patcher" verschwunden ist.
- **README:** englische Prosa in `Features`, `Tech Stack`, `Installation`,
  dem Watchdog- und dem Drop-in-Abschnitt sowie in `Running Tests` und
  `Related` ist deutsch geworden; die doppelte Einleitung vor `## Features`,
  die Installation und Unit-Liste ein zweites Mal erzählte, ist zusammengezogen.
  Der Selbsttest von `octomap_feed.py` ist in `Running Tests` nachgetragen.

**Sichtbar am Gerät** — das ist der einzige Teil, der nicht reine Prosa ist:

- Die Meldungen der Manipulator-Diagnose (`manipulator_diagnostics`) sind
  englisch. In Cockpit steht also `arm switched off - gripper without supply`
  statt „Arm ausgeschaltet – Greifer ohne Versorgung", und die Werte
  `grip_detected`/`busy`/`moving` melden `unknown` statt `unbekannt` — damit
  stehen sie in derselben Sprache wie ihre Nachbarn (`running`, `stopped`,
  `live`, `dead`), die schon immer englisch waren. Die Tabellen in der README
  zitieren die neuen Zeichenketten. Level, Struktur und `display=inactive`
  sind unverändert.
- Die Ausgaben von Installer, `wakeup.sh` und `shutdown.sh` sind englisch, wie
  die `>>> `-Zeilen der Workspace-Skripte. Die Rückfragen heißen jetzt
  `[y/N]` statt `[j/N]`; `j` wird weiterhin als Ja akzeptiert, damit eine
  eingeübte Eingabe nicht ins Leere läuft.

Gegengeprüft: `bash -n` über alle drei Shell-Skripte und den extrahierten
Watchdog-Wrapper, `compile()` über den eingebetteten Patcher, `black --check`
gegen die Root-Konfiguration über alle vier Python-Dateien, `yaml.safe_load`
über `robot.yaml` und die drei Selbsttests (`manipulator_diagnostics`,
`rg6_grip_bridge`, `octomap_feed`) — alle grün.

## 2026-08-24 (Aufräum-Einträge raus)

- **Der Installer räumt keine Alt-Units mehr weg.** Die Migration auf das
  `clearpath-custom-*`-Prefix und die abgeschafften Units sind auf a200-0553
  durch, also trägt das Skript die Listen nicht länger mit. Entfallen sind
  `OLD_UNITS` (neun unpräfigierte Namen: `clearpath-set-update-rate`,
  `rg6-bringup`, `ur-dashboard`, `ur-state-manager`, `arm-controllers`,
  `joint-states`, `manipulators-watchdog.service`/`.timer`,
  `robot-yaml-update`), `RETIRED_UNITS` (`clearpath-custom-rg6-bringup`),
  `OLD_FILES` (`set-update-rate.py`, `wait-for-clearpath.sh`,
  `rg6-bringup.sh`), `OLD_DIRS` (`joint-states.service.d`), das Wegräumen
  der `.bak`-Leichen sowie die beiden Einzelblöcke für
  `clearpath-custom-arm-controllers` und
  `clearpath-custom-robot-yaml-update`. 88 Zeilen weniger.

  Vorher am Roboter gegengeprüft (2026-08-24, rein lesend über SSH): alle
  zwölf Unit-Namen ohne Datei in `/etc/systemd/system`, ohne Eintrag in
  `systemctl list-unit-files` und `is-active = inactive`; alle fünf Wrapper
  in `/usr/local/bin` fort; `/etc/systemd/system/joint-states.service.d`
  fort; keine `manipulators-watchdog.*.bak.*` und keine
  `clearpath-custom-rg6-bringup.service.bak*`. Was noch dort liegt, sind
  Backups AKTUELLER Artefakte (`clearpath-custom-ur-dashboard.service.bak.a2`,
  `clearpath-custom-setup.py.bak.a4`) -- die pflegt `prune_backups` weiter.

  Damit fällt auch das Migrationsfenster weg: ein Installer-Lauf stoppt
  keine Services mehr, bevor er die neuen schreibt. Wer eine Maschine mit
  altem Stand nachziehen muss, nimmt die Liste aus diesem Eintrag oder einen
  Checkout vor diesem Commit.

- Kleinkram im selben Zug: die README beschrieb das Wegräumen als laufendes
  Verhalten, der Log-Hinweis `journalctl -t robot-yaml-update -b` zeigte auf
  einen abgeschafften Dienst, und drei Kommentare verwiesen auf das nun
  gelöschte `RETIRED_UNITS`.

## 2026-08-24 (Reste des Tool-DO-Greifers)

- **Die Brücke veröffentlichte einen geschlossenen Greifer, wo sie gar
  nichts gemessen hatte.** Die URCap wirft keinen Fault, wenn am
  Tool-Anschluss nichts anliegt -- sie ANTWORTET, mit ihrem eigenen
  Kennzeichen für "keine Messung": `rg_get_width -> -999.0`,
  `rg_get_status -> -1`. Das lief durch `angle_from_width`, das die Weite
  KLEMMT statt zu extrapolieren, und kam als `1,25478 rad` heraus -- der
  vollständig geschlossene Greifer. Am 2026-08-24 am a200-0553 gemessen,
  Arm auf `POWER_OFF`: `rg6_finger_joint = 1,25478` mit 5 Hz auf
  `manipulators/endeffectors/joint_states`, vom Relay weiter auf
  `platform/joint_states` (in 8 s 34 Nachrichten) -- also in RSP, TF und der
  Planungsszene von `move_group`, bei stromlosem Greifer.
- Ursache ist eine mit `rg6_control` weggefallene Sperre: der alte Treiber
  hatte die Totschwelle auf AI2/AI3 (`dead_input_threshold`), an ihre Stelle
  trat nichts. Die Brücke verliess sich darauf, dass ein toter Greifer eine
  Exception wirft. Er wirft keine. `Rg6State.readable` prüft das jetzt
  (Status + Nennbereich); ist die Antwort keine Messung, bleibt das GELENK
  still -- der Zustandstopf geht weiter raus, damit die Manipulator-Diagnose
  "Greifer stromlos" von "Brücke tot" unterscheiden kann. Im Selbsttest
  festgenagelt, mit den live gelesenen Werten.
- **`clearpath-custom-joint-states.service` ordnete sich nach einer gelöschten
  Unit.** `After=clearpath-custom-rg6-bringup.service` -- die räumt derselbe
  Installer 1100 Zeilen weiter oben weg. systemd trägt so einen Namen klaglos
  mit (per `systemctl show` am Roboter bestätigt), ordnet aber gegen nichts:
  die Reihenfolge, die der Kommentarblock daneben ausführlich begründet, war
  unbemerkt weg. Steht jetzt auf `clearpath-custom-rg6-grip-bridge.service`,
  der heutigen Greiferquelle -- und zwar in `After=` UND `PartOf=`: die
  Brücke startet für sich allein neu, und genau dann resubscribed der Relay
  unter rmw_zenoh nicht.
- **`rg6_msgs` wird nicht mehr gebaut.** Das Paket trug `GripperState` und
  `Grip` für den Tool-DO-Treiber. Kein Paket deklariert es mehr als
  Abhängigkeit, kein Knoten baut den Typ; am Roboter gegengeprüft:
  `<ns>/rg6/state` existiert nicht mehr, nur `rg6/bridge_state`.
  (Das Paket selbst liegt in `onrobot-rg6` und ist damit verwaist -- das zu
  löschen ist eine Entscheidung dort, nicht hier.)
- `scripts/rg6_kennlinie.py` sagt jetzt, wofür es noch da ist. Sein Kopf
  begründete sich mit der AI2-Kennlinie in `rg6_joint_state_broadcaster.cpp`
  -- eine Datei, die es nicht mehr gibt -- und gab als Erholung aus einem
  festgefahrenen Greifer `set_tool_power` an, einen Service aus `rg6_control`.
  Offen ist an R19 nur noch der offene Anschlag (Modell 159 mm, Messschieber
  ~151 mm), und dafür braucht es AI2 nicht.
- Kleinkram im selben Zug: die README zählte `clearpath-custom-rg6-bringup`
  unter den Units auf, die der Installer ANLEGT (er löscht sie), und liess
  die Brücke weg; der Wrapper-Kommentar nannte `topic_tools`-Relays, obwohl
  das Launch aus QoS-Gründen ausdrücklich den eigenen `joint_state_relay`
  nimmt.


### Der Timeout-Zweig in `shutdown.sh` war tot (ROBOTER-TODO R4)
- **`call_trigger` konnte einen nicht erreichbaren Service nicht als solchen
  melden.** Der Exit-Code wurde als `… || true` in die Kommandosubstitution
  gelegt und danach mit `rc=$?` gelesen — das liest den Status der *Zuweisung*,
  und der ist immer 0. Der `if [ "$rc" -eq 124 ]`-Zweig konnte also nie feuern.

  Folge war keine verpasste Fehlererkennung, sondern eine **falsche Diagnose**:
  ein toter Service lief in den `grep`-Zweig und meldete „kein success=true"
  statt „Timeout — Service nicht erreichbar". Wer beim Parken des Arms sucht,
  sucht dann an der falschen Stelle.

  `wakeup.sh` hatte das richtige Muster längst, inklusive Begründung im
  Kommentar. `call_trigger` ist in beiden Skripten jetzt zeichengleich.

  Gegengeprüft mit einem gestubbten `timeout`, das 124 liefert: die gepatchte
  Fassung meldet „Timeout — Service nicht erreichbar", die alte „kein
  success=true".

### Der Installer nimmt den Checkout vor GitHub-main (ROBOTER-TODO R6)
- **`octomap_feed.py` und `manipulator_diagnostics.py` wurden per `curl` von
  `refs/heads/main` geholt, die lokale Repo-Kopie war nur der Fallback.** Wer
  den Installer aus dem Checkout laufen liess, bekam damit nicht, was im
  Checkout stand — genau das Muster, aus dem der `octomap_feed.py`-Drift in
  drei Fassungen entstanden ist (`min_depth` 0.15 vs. 0.35).

  Beide Blöcke benutzen jetzt `repo_file`, das es seit dem RTDE-Recipe schon
  richtig herum macht: neben dem Skript, dann `~/husky-custom-setup`, erst
  danach das Netz. Ist die gefundene Datei **kein gültiges Python**, wird sie
  verworfen und *nicht* still durch `main` ersetzt — ein kaputter Checkout soll
  auffallen.

- **Neu: `--verify`.** Hasht die ausgerollten Kopien gegen den Checkout und
  beendet sich; rein lesend, ohne root, ohne Netz. Diese Artefakte hängen an
  keinem Git — dass sie inhaltlich passen, wusste man bis jetzt nur durch
  Hinsehen. Abgedeckt sind `octomap-feed`, `manipulator-diagnostics`,
  `rg6-grip-bridge`, `rg6_finger_kinematics.json`,
  `rtde_input_recipe_no_tool.txt` und `rg6-moveit-patch` (letzteres gegen den
  onrobot-rg6-Workspace). Exit 0 = deckungsgleich, 1 = Abweichung.

  Am Roboter gefahren (2026-08-20): alle sechs Artefakte deckungsgleich mit dem
  dortigen Checkout `464ed63`. Der Negativfall ist mitgeprüft — eine
  hinzugefügte Zeile in der Quelle wird als `ABWEICHUNG` mit Exit 1 gemeldet.

### Patcher-Schritt 2 bleibt, und jetzt steht auch dabei warum
- **`fix_realsense_mesh_uris` galt kurzzeitig als No-op und war es nie.** Die
  Annahme lautete, upstream habe `file://` -> `package://` in
  `clearpath_sensors_description` **2.9.8** selbst repariert; der Schritt kam
  deshalb am 2026-08-20 heraus und noch am selben Tag wieder herein.

  Am Gerät nachgesehen, indem beide `.deb` ausgepackt und gelesen wurden:

  | Paket | Quelle | d415 / d435 / d455 / d456 |
  |---|---|---|
  | 2.9.8 | packages.ros.org | `file://` — alle vier |
  | 2.9.15 | packages.clearpathrobotics.com | `file://` — alle vier |

  Upstream hat es also nie repariert. Die falsche Ablesung kam aus dem
  Offboard-**Container**, dessen `Dockerfile` (husky-offboard) dieselbe
  Ersetzung beim Bau vornimmt — gelesen wurde die gepatchte Datei, nicht das
  Paket.

- **Zwei naheliegende Proben taugen nicht als Beleg**, und beide sind an dem Tag
  gefahren worden: „die URDF baut fehlerfrei" (xacro öffnet nie ein Mesh —
  selbst ein erfundenes `package://` läuft mit Exit 0 durch) und „das Mesh ist
  in Foxglove sichtbar" (zeigt den Zustand *nach* dem letzten Patcherlauf; der
  Patch ist persistent und bleibt stehen, bis dpkg ihn überbügelt).
  Entscheidend ist allein der Inhalt des `.deb`.

- **Die Begründung im Docstring war zudem falsch.** Nicht der
  `resource_retriever` lehnt `file://` ab — der kann es —, sondern die
  `asset_uri_allowlist` der `foxglove_bridge`, die mit `^package://` beginnt.
  Per `fetchAsset` gemessen: `package://…/d435.dae` -> status 0, 15 782 439
  Byte; dieselbe Datei als `file://` -> status 1. Die Wirkung ist rein visuell
  (Kameramodell im Foxglove-3D-Panel); `<collision>` ist eine Box-Primitive.

  Alles davon steht jetzt im Docstring der Funktion, samt „NICHT ENTFERNEN".

## 2026-08-23 (Bezeichner auf Englisch)

- **Die Bezeichner dieses Pakets sind englisch**, die Prosa bleibt deutsch —
  dieselbe Konvention wie in `sdk/skill-tree` und wie CLAUDE.md sie vorgibt
  ("Doku ist deutsch"). Umbenannt wurden Funktionen, Klassen, Konstanten,
  Parameter und lokale Variablen; Docstrings und Kommentare NICHT.
- **Was ein Programm AUSGIBT, bleibt deutsch**: Abschnittsmarken, JSON-Feld-
  namen und Log-Meldungen sind der Bericht an den Menschen, nicht Code.
- Umbenannt wurde mit einem `tokenize`-Werkzeug (nur NAME-Token), nicht per
  Regex — deshalb ist kein Kommentar und kein String mitgewandert. Drei
  Stellen, die `tokenize` NICHT sieht, wurden eigens nachgezogen:
  f-String-Interpolationen (unter Python 3.11 ist ein f-String EIN Token),
  die Parameternamen in `pytest.mark.parametrize` und Bezeichner, die
  quelltextlesende Tests als String erwarten.
- Gegengemessen: `uv run pytest` steht unverändert bei 2465 passed,
  3 skipped — derselbe Stand wie vor der Umbenennung.

## [Unreleased]

## [0.2.0] - 2026-08-19

### README-Greiferteil auf den Ist-Zustand
- **Der Diagnose-Abschnitt der README stand noch vor der URCap-Uebergabe.** Er
  nannte `rg6_msgs/GripperState` als Zustandsquelle, begründete die
  Spannungsprobe mit `rg6_control` und dem `rg6_joint_state_broadcaster`, liess
  den Wrapper den `onrobot-rg6`-Workspace für `rg6_msgs` sourcen und gab dem
  Bediener zweimal das Rezept `rg6_control/set_tool_power` + `open`.

  Nichts davon existiert. Der schärfste Fall: `manipulator_diagnostics.py`
  prüft im Selbsttest ausdrücklich `assert "set_tool_power" not in
  dead_on.message, "der Service existiert nicht mehr"` -- der Code testete
  also aktiv gegen die Empfehlung, die die README gab. Jetzt steht dort, was
  gilt: Zustand als JSON auf `rg6/bridge_state`, Tool-Spannung als
  Versorgungsfrage (nicht als Weitenquelle, AI2 ist bis zu 17 mm falsch
  geeicht), und als Ausweg das URCap-Programm am Panel.
- **`auto_recover` holt den Greifer nicht mit hoch.** Die README behauptete
  das über die Programmflanke von `rg6_control`; die gibt es nicht mehr, und
  kein ROS-Service kann die Tool-Versorgung setzen.
- **Historische Bezüge aus den Quellkommentaren entfernt** (`installer`,
  `manipulator_diagnostics.py`, `rg6_grip_bridge.py`): das wiederholte "seit
  dem rg6_control-Ruhestand" steht hier und muss nicht in jeder Datei noch
  einmal erzählt werden. Die Begründungen selbst sind geblieben, nur ohne
  Vorgeschichte. Kommentare an **Aufräumcode** (`RETIRED_UNITS`, das
  Entfernen der abgelösten Units) bleiben unverändert -- dort *ist* die
  Migration die Funktion.
- Nebenbei korrigiert: der Build-Kommentar nannte `rg6_control` weiterhin
  "Treiber/Broadcaster"; das Paket enthält heute den Simulations-Greifer, die
  joint_state-Hilfsnodes und `rg6_moveit_patch`.

### Boot-Patcher von 5 auf 3 Schritte

- **Die Manipulator-Analyzer stehen in `robot.yaml`, nicht mehr im Patcher.**
  Neu unter `platform.extras.ros_parameters.diagnostic_aggregator`: die
  AnalyzerGroup `Manipulator` mit `Arm` und `Gripper`. Der Generator merged sie
  in die erzeugte `diagnostic_aggregator.yaml` und flacht die Verschachtelung
  selbst auf die Punkt-Keys ab, die ROS erwartet. Im Container nachgemessen:
  **alle 10 Analyzer-Keys wertgleich** zum früheren Patch, die 20
  Upstream-`platform.analyzers.*` und die 8 Sensor-Keys unangetastet.

  **Eine Kopplung entfällt dabei:** `add_manipulator_analyzers` lief nur, wenn
  `clearpath-custom-manipulator-diagnostics.service` installiert war -- die
  Unit-Datei war der Feature-Schalter. `robot.yaml` kennt diese Bedingung
  nicht. Läuft der Diagnose-Node nicht, zeigt Cockpit die Gruppe jetzt als
  STALE, statt sie verschwinden zu lassen; Rückbau = Block entfernen.
- **Die foxglove-Allowlist auch -- der Trick ist eine backslash-freie Regex.**
  Bisher galt der Patch als unverschiebbar, und der Grund stimmte: der
  `ParamWriter` des Generators schreibt Skalare korrekt in Single-Quotes,
  serialisiert **Listen** aber über Pythons `repr` und verdoppelt dabei jeden
  Backslash. YAML-Single-Quotes lesen ihn literal zurück, aus `\w` wird ein
  totes Muster. Gemessen: die generierte `foxglove_bridge.yaml` ist dadurch
  **im Auslieferungszustand kaputt** -- ihre Allowlist matcht keine einzige
  `package://`-URI, gepatcht oder nicht.

  **Der Node-Default wäre in Ordnung -- er kommt nur nie zum Zug.** Am
  laufenden `foxglove_bridge` gemessen (`ros2 param get`): ohne jede Config
  meldet er `^package://(?:[-\w%]+/)*[-\w%.]+\.(...)$`, also die korrekte
  Fassung. Clearpaths Vorlage
  (`clearpath_diagnostics/config/foxglove_bridge.yaml`) **setzt** den Parameter
  aber immer, und ein gesetzter Parameter verdeckt den Default; mit der
  generierten Datei sieht der Node `[-\\w%]`. Weglassen ginge nur, wenn der
  Schlüssel gar nicht generiert würde -- `ros_parameters` kann nur
  überschreiben, nicht löschen. Dieser Eintrag ist also weder Dublette noch
  zusätzliche Einschränkung, sondern stellt her, was ohne den Writer-Bug
  ohnehin gälte.

  **Ein Generator-Upgrade hilft nicht.** Am neuesten Upstream-Tag 2.9.15
  nachgesehen (sieben Releases nach unserer 2.9.8, `jazzy`-HEAD identisch):
  `write_key_value_pair` ist weiterhin `self.write(f'{key}: {value}')` ohne
  Listenbehandlung und ohne Escaping, und die Vorlage setzt
  `asset_uri_allowlist` weiterhin mit der `\w`-Regex. Der Eintrag ist damit
  ein Dauerzustand, kein Uebergangs-Workaround.

  Der Ausweg braucht keinen Backslash: `[A-Za-z0-9_]` statt `\w`, `[.]` statt
  `\.`. Der Wert geht dann unverändert durch den Writer. Belegt gegen die
  echte Engine -- `foxglove_bridge` hält die Muster als
  `std::vector<std::regex>` und vergleicht mit `std::regex_match`
  (`utils.hpp::isWhitelisted`): auf einem Korpus aus 14 Treffern und
  Nicht-Treffern **null Divergenzen** zur korrekten `\w`-Fassung, inklusive
  des Nicht-ASCII-Falls, in dem sich Pythons `re` und C++ unterscheiden.
- **Der Patcher ist damit auf drei Schritte geschrumpft** (Mesh-URIs,
  joint_states-Bus, RG6-SRDF) und rund 6,7 KB kleiner. Mit `set_scalar_line`
  und `add_manipulator_analyzers` sind auch `FOXGLOVE_YAML`,
  `FOXGLOVE_ALLOWLIST`, `AGGREGATOR_YAML`, `MANIPULATOR_ANALYZERS`,
  `MANIPULATOR_UNIT_FILE`, `MANIPULATOR_STATUS_PREFIX` und der ungenutzte
  `tempfile`-Import entfallen. Was bleibt, patcht **apt-Pakete** (dort hat
  `robot.yaml` prinzipiell keinen Hebel) oder die SRDF.
- Die Wache vor dem einmaligen Patcher-Lauf im Installer hängt jetzt an
  `robot.yaml` statt an der generierten `foxglove_bridge.yaml` -- die patcht er
  ja nicht mehr. Die verbliebenen Schritte sind einzeln gegen fehlende Dateien
  abgesichert.

### MoveIt-Greiferwerte in robot.yaml

- **`robot.yaml` trägt den GripperCommand-Controller des RG6.** Neu unter
  `manipulators.moveit.ros_parameters.move_group`: der
  `moveit_simple_controller_manager`-Eintrag
  `manipulators/rg6_gripper_controller` (Typ `GripperCommand`, `action_ns`
  `gripper_cmd`, `max_effort` 60 N) und
  `robot_description_planning.joint_limits.rg6_finger_joint` (TOTG braucht ein
  Beschleunigungslimit, sonst scheitert die Zeitparametrierung der
  gripper-Gruppe). Beides stand bisher im `rg6_moveit_patch` und wurde nach
  jeder Generierung nachträglich in die erzeugte `moveit.yaml` geschrieben.
  Im Container nachgemessen: das Ergebnis ist identisch bis auf die
  Reihenfolge in `controller_names`. Derselbe Weg, den 2026-07-29 schon die
  Occupancy-Map-Parameter genommen haben (A4).

  Zwei Dinge, die man dabei wissen muss: `merge_dict` **verlängert Listen**,
  statt sie zu ersetzen -- in `controller_names` darf deshalb nur *unser*
  Controller stehen, der Arm-Controller käme sonst doppelt. Und weil
  `clearpath-robot-check` `robot.yaml` per md5 im Sekundentakt beobachtet,
  startet diese Aenderung am Roboter den kompletten Stack neu.
- **Der Installer-Schritt 4 patcht nur noch die SRDF.** Kommentar und
  Docstring von `run_rg6_moveit_patch` sagen jetzt, warum die SRDF den Umweg
  über das Tool braucht und die `moveit.yaml` nicht: `clearpath_config` kennt
  das Wort `srdf` nicht, und der Greifer-Enum hat keinen RG6.

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

---

**Vor der Einführung von SemVer (2026-08-19)** wurde nach Datum
geführt. Die Abschnitte darunter behalten ihre Datumsüberschrift — ihnen
nachträglich Versionsnummern zu geben, würde eine Release-Historie
erfinden, die es nicht gab.
- **SemVer eingeführt.** Version auf `0.2.0`, dieses Changelog folgt
  [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Tag `v0.2.0`.
  Ältere Abschnitte behalten ihre Datumsüberschrift — ihnen nachträglich
  Versionsnummern zu geben, würde eine Release-Historie erfinden.
- **README nach dem Workspace-Schema** (readme.so): Features · Tech Stack ·
  Installation · Usage · Running Tests · Related · Versioning · License. Die
  vorhandene Prosa ist erhalten und unter den passenden Abschnitt gewandert.
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
