# Changelog

Format after [Keep a Changelog](https://keepachangelog.com/),
versioning after [SemVer](https://semver.org/).

## 2026-08-30 (ruff resolves the same settings from anywhere)

- **`target-version = "py311"` now stands in `[tool.ruff]`.** Ruff infers it from `project.requires-python`
  when absent -- which the virtual workspace root has no `[project]` table to supply, so a run through the ROOT
  config resolved to 3.10 while a run inside this package resolved to 3.11 (measured 2026-08-30,
  `ruff check --show-settings`). The pre-commit hook passes `--config <workspace-root>`, so 3.10 was the
  version every commit got checked against.

## 2026-08-29 (the package docstring names the launch directory)

- **The docstring refers to the repo's `launch/`** rather than `../launch/`, which reads as a path relative to the
  package directory and does not resolve from there.

## 2026-08-29 (the package run can measure coverage again)

- **`-p no:cov` is gone from `addopts` in `[tool.pytest.ini_options]`.** It disabled the pytest-cov plugin
  outright, so `pytest --cov` in this package aborted with `unrecognized arguments: --cov`. The package run is
  where a suite is measured on its own, and where the E2E marks are reachable at all -- the root run deselects
  them.
- The reason the line carried applied to the SYSTEM interpreter, whose pytest-cov did not match its coverage.
  The workspace venv is not that interpreter: it carries pytest-cov 5.0.0 against coverage 7.15.1.
- **15 packages carried the line, and they were not found in one go**: `grep --cov` does not match `no:cov`, so
  the first pass found five and a layered measurement died on the rest three quarters of the way through.
  `.claude/skills/coverage-report` now checks every member for it BEFORE measuring anything.
- **`.gitignore` gained `.coverage` and `.coverage.*`** -- a justified package extra, not a mass dump: a package
  run with `--cov` writes them here. The workspace-wide measurement writes to `.coverage-data/` at the root.

## 2026-08-27 (the package speaks English)

- **Assertion and skip messages are English.** They are what somebody reads who does not know the code, and they
  stand in tickets next to English library messages. The module docstrings were already English, so a failing test
  used to answer half in one language and half in the other.
- **The comments inside the embedded shell scripts are English** -- the retry loops in the `nav_e2e` files and the
  measured rationales beside them (drive window, measurement threshold, always steer towards the centre of the map).
  German decimal commas became points inside those sentences.
- **The two `ValueError` messages of `rslidar_config.render` are English.** The `match=` expectations in
  `test_rslidar_config.py` key on `lidar` and `common`, so they were unaffected.
- **`make_map` writes an English header** into the generated `.pgm` and `.yaml`; `maps/leerer_raum.*` is regenerated
  so the checked-in files match their generator. Only the header comment differs, the pixel data is unchanged.
- **No transliterated umlauts are left** (`laeuft`, `wuerde`, `gehoeren` and four more). The file name
  `leerer_raum.*` is deliberately kept: it is quoted in `docs/superpowers/plans/2026-08-22-nav2-rs16.md` and in
  `ROBOTER-TODO.md`, and renaming it would separate those records from what they cite.

## 2026-08-26 (the black section stops repeating the workspace rule)

- **`[tool.black]` carries no copy of the workspace rule any more.** The section itself is unchanged --
  `line-length = 120` and the same `force-exclude` -- but the rationale that stood verbatim in every sub-repo
  is gone. Why the section has to exist is written down once: in the workspace `CLAUDE.md`, and in this file's
  2026-08-25 entry *Black formats this repo the same way from anywhere*.
- **`authors` is indented four spaces**, like every other array in the file.
- **`requires-python` is `>=3.11`.** `contract/robot-contract` and `apps/hrl` import `typing.Self` (PEP 673),
  which does not exist before 3.11. Measured on 3.10.19: `from typing import Self` raises
  `ImportError: cannot import name 'Self' from 'typing'` -- at import time, so the module does not load at all, and
  no `from __future__ import annotations` helps. Thirteen packages depend on `robot-contract`, so a `>=3.10` beside
  it was not resolvable on 3.10 anyway; all 19 workspace packages now carry the same floor.

## 2026-08-25 (the nav tests address the counterpart container)

- **The three `nav_e2e` files point at `husky-offboard-mock-robot-1`.** `nav2_*`, `ekf_node` and the RS16 driver run
  in the simulated robot, which is a service of its own now.

## 2026-08-25 (Black formats this repo the same way from anywhere)

- **`[tool.black]` now stands in this repo's `pyproject.toml`.** Black takes the first directory
  containing a `.git` as its project root, so a run from inside this repo fell back to Black's own
  88-column default while the workspace runs at 120. The pre-commit hook was unaffected -- it passes the
  root config explicitly -- but an editor or a bare `black` was not.

## 2026-08-25 (the base lock moves to robot_contract)

- **`exclusive_base` now takes the shared lock from `robot_contract.base_testing`.** A conftest is directory-scoped, so the lock defined here serialised this package and nothing in `apps/robot-mcp`, which drives the same base. The fixture stays as the local name; the rendezvous is shared.
- **`filelock` is no longer imported undeclared.** It arrives through `robot-contract[testing]` in the new dev group -- test-only, so nothing extra is installed onboard.

## 2026-08-24 (.gitignore normalised to the workspace base)

- **`.gitignore` now uses the workspace's lean 8-line base** (`__pycache__/`, `*.py[cod]`, `*.egg-info/`, `build/`, `dist/`, `.venv/`, `.pytest_cache/`, `.DS_Store`). ROS extras: `install/`, `log/`, `*.pcd`, `COLCON_IGNORE`, `AMENT_IGNORE`.

## 2026-08-24 (pyproject.toml normalised)

- **`pyproject.toml` follows the workspace's canonical section order now** (`[build-system]`, `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, `[project.urls]`, `[dependency-groups]`, `[tool.uv.sources]`, `[tool.setuptools.*]`, `[tool.pytest.*]`); the `[project]` keys follow PEP 621 order (`name`, `version`, `description`, `readme`, `requires-python`, `authors`, `dependencies`). Pure reordering -- every comment and value is unchanged.
- **`readme = "README.md"` added** so the long description is packaged.

## 2026-08-24 (Author metadata added)

- **`authors = [{ name = "Hannes Philip Voss", email = "mail@hannesvoss.de" }]`
  added** to `pyproject.toml`, the workspace-wide form. The package had no
  `authors` block before. Metadata only, no behaviour change.

## 2026-08-24 (pytest config block, canonical form)

- **`[tool.pytest.ini_options]` added** with `pythonpath=["src"]`,
  `testpaths=["tests"]`, `addopts="-p no:cov"`, and the `nav_e2e` marker
  registered. The suite had been running off the root config and the editable
  install alone, and `nav_e2e` was an unregistered marker (PytestUnknownMark
  warning); the package now carries its own config like every other package
  (CLAUDE.md, "Ein neues Paket anlegen").
- No behaviour change; 35 passed, 16 skipped (the `nav_e2e` driving tests skip
  cleanly without a running base) from within the package.

## 2026-08-24 (Build backend aligns to the workspace norm)

- **Switched from `hatchling` to `setuptools.build_meta`.** Matches the
  `apps/_template` build config (`[tool.setuptools.packages.find] where =
  ["src"]`); the `hatchling` instance was unlisted drift against the workspace
  norm (CLAUDE.md, "Ein neues Paket anlegen").
- **`requires-python` lowered from `>=3.11` to `>=3.10`.** The workspace floor
  is `>=3.10` (the venv is 3.11); `>=3.11` was drift without a recorded reason.
- No behaviour change; 35 tests still green.

## 2026-08-24 (README in English)

- **The README is now fully in English.** Per CLAUDE.md, `README.md` and
  `CHANGELOG.md` are English everywhere; a README is current state, so it was
  translated in one piece rather than paragraph by paragraph.
- Prose only, no behaviour change.

## [Unreleased]

### Hinzugefuegt
- **Nav2 hat einen Verbraucher am `/twin/*`-Draht (2026-08-22).** Der
  `plan_server` uebersetzt seit Protokoll v7 `/twin/nav_cmd` auf die hier
  gestarteten Nav2-Actions, und `robot-mcp` gibt sie einem Agenten als acht
  Skills. An dieser Schicht aendert das nichts -- sie bleibt der Ort, an dem
  Nav2 und der Sensorpfad konfiguriert und gestartet werden. Wichtig ist die
  Richtung: der Verbraucher baut **keinen** zweiten Planer, er setzt Ziele
  auf `navigate_to_pose`, `navigate_through_poses`, `spin`, `backup` und
  `compute_path_to_pose` ab.
- **Der Stand aus diesem README ist damit auch der Stand der Skills.** Ein
  Agent, der `nav_to_pose` fahren kann, faehrt gegen eine synthetische Karte
  ohne Lokalisierung und ohne Hindernisse. `apps/robot-mcp/README.md` sagt
  das an seiner Stelle noch einmal, damit niemand aus "der Skill existiert"
  auf "der Roboter ist lokalisiert" schliesst.


### Fixed
- **`odom_topic` im `controller_server` gesetzt — das war die Wurzel.** Der
  Nav2-Default ist `odom`, im Namespace also `/a200_0553/odom`, und darauf
  publiziert **niemand** (`Publisher count: 0`, gemessen). Im `bt_navigator`
  stand der Wert richtig, im `controller_server` fehlte er — dieselbe
  Pro-Knoten-Falle wie bei `enable_stamped_cmd_vel`, zwei Wochen später
  nochmal.

  Es scheiterte ohne eine einzige Fehlermeldung: `speed` blieb konstant 0,
  und jeder Regler, der die Ist-Geschwindigkeit braucht, regelte blind. Der
  `RotationShimController` beschleunigte in jedem Zyklus aufs Neue von null
  und kam über genau einen Schritt nicht hinaus — **kommandiert wurden
  0,05 rad/s statt 0,8** (`max_angular_accel` 1,0 × 0,05 s Zykluszeit). Der
  Husky drehte sich mit 2,9°/s; eine 180°-Wende hätte 63 s gedauert. Nach
  10 s schlug der Fortschrittswächter zu, brach ab, der Baum plante neu, und
  das Karussell begann von vorn.

  Gemessen, gleiches Experiment vorher/nachher: ein Ziel 3,76 m **hinter**
  dem Roboter lief vorher in ein Timeout (105 s, nur 1,5 m gefahren) und
  danach in **25 s, `SUCCEEDED`, volle 3,54 m**. Die `nav_e2e`-Suite fiel von
  157 s auf 82 s.

  Als Quelle dient `platform/odom/filtered`, nicht die rohe `platform/odom`:
  der EKF liefert auch die TF `odom → base_link`, damit kommen Pose und
  Geschwindigkeit von derselben Stelle. `bt_navigator` wurde mit umgestellt.

  **Aufgefallen ist es an einer Beobachtung am Bildschirm** — „er dreht sich,
  aber sehr langsam" —, nicht an einem Log und nicht an dieser Suite. Der
  Verdacht davor lag beim Skid-Steer-Antrieb und war falsch: die Kette
  cmd → Räder → Odometrie ist im Mock exakt konsistent (befohlen 0,5 rad/s,
  gemeldet 0,49999). Die Nachfrage hat dafür eine andere Lücke sichtbar
  gemacht, s. R37.

- **`FollowPath` ist jetzt der `RotationShimController` mit RPP als
  `primary_controller`.** Der Shim dreht den Husky vor dem Losfahren auf die
  Pfadrichtung ein — genau das, was ein Skid-Steer gut kann. Ohne ihn blieb
  er bei großen Richtungsänderungen liegen: Ziel (−2|2) aus (1,93|1,78) fuhr
  in 51 s ganze 0,06 m und meldete dann `ABORTED`, während ein Ziel geradeaus
  in derselben Runde in 12 s durchlief. Nach beiden Korrekturen läuft dasselbe
  Ziel in 26 s über volle 3,72 m.

- **`yaw_goal_tolerance` auf 3,15 — die Zielorientierung wird bewusst nicht
  erzwungen.** RPP ist ein reiner Positionsfolger und dreht am Ziel nicht
  nach; der Regler kennt dafür nicht einmal einen Parameter (am laufenden
  `controller_server` abgefragt). Mit enger Toleranz stand der Husky auf der
  Zielposition, 155° verdreht, und kam nie hinein: Ziel-Yaw 0, End-Yaw
  −2,709 rad bei nur 0,237 m Positionsabweichung. Das Goal lief bis zum
  Timeout, und die Recoveries drehten ihn zufällig weiter, bis es zufällig
  passte — 12 Recoveries und 121 s für 2 m. Ohne Scans steht die
  Lokalisierung ohnehin auf reiner Radodometrie; eine 14°-Endtoleranz wäre
  eine Genauigkeit, die die Sensorik nicht hergibt.

- **`default_server_timeout` von 20 auf 200 ms.** Der Wert ist in
  Millisekunden, und 20 ist unter Containerlast zu knapp. Beobachtet: der
  Baum gab auf, und **0,28 s später** meldete der `controller_server`
  `Reached the goal!` — das Ergebnis lautete `ABORTED` bei einer
  Endabweichung von 0,226 m, also innerhalb der 0,25er Toleranz. Ein Rennen,
  das sporadisch auftritt; wer nur den Status liest, sucht den Fehler beim
  Regler.

### Added
- `test_the_ground_frame_matches_the_wheel_geometry` — prüft, dass
  `base_footprint` zur Radachse **und** zum `wheel_radius` aus
  `control.yaml` passt. URDF und Radcontroller sind zwei Quellen, die
  nichts voneinander wissen; laufen sie auseinander, ist nicht nur die
  Darstellung falsch, sondern auch die Odometrie.

  Anlass war die Beobachtung, dass der Husky in RViz 13,2 cm im Boden
  steckt. Das URDF ist daran unschuldig (0,03282 − 0,1651 = −0,13228, exakt
  der `base_footprint`-Wert); der Versatz kommt vom EKF, der mit
  `base_link_frame: base_link` und `two_d_mode: True` **base_link** auf
  z = 0 pinnt. Clearpaths Konvention, über `robot.yaml` nicht einstellbar,
  für Nav2 folgenlos. Ausführlich im README unter „Frames".
- `test_navigates_to_a_goal_it_has_to_turn_around_for` — dreht den Husky
  absichtlich vom Ziel weg und prüft, ob er ankommt. Der Nachbartest fährt
  bewusst immer zur Kartenmitte, also praktisch geradeaus, und hat deshalb
  keine der obigen Fehlfunktionen bemerkt.
- `test_the_controller_actually_receives_odometry` — prüft, dass auf dem
  eingestellten `odom_topic` auch wirklich jemand **publiziert**. Ein Topic
  taucht in ROS 2 schon in `topic list` auf, wenn es nur abonniert wird; ein
  statischer Parametertest kann einen falschen Topicnamen nicht von einem
  richtigen unterscheiden.
- `test_every_odom_consumer_reads_the_ekf` — dieselbe Pro-Knoten-Liste wie
  bei `cmd_vel`, damit der nächste hinzukommende Knoten nicht wieder
  vergessen wird.

- `enable_stamped_cmd_vel` steht jetzt auch im `behavior_server`, nicht nur
  im `controller_server`. Der Parameter gilt **pro Knoten**: ohne ihn
  publizierten `spin` und `backup` `geometry_msgs/Twist`, während
  `twist_mux` ausschließlich `TwistStamped` abonniert — die
  Recovery-Kommandos erreichten die Basis also nie, und der Roboter wäre in
  einer Sackgasse stehen geblieben, statt sich freizufahren.

  Am 2026-08-22 im Mock gemessen. Vorher trug `/a200_0553/cmd_vel` beide
  Typen (`controller_server` → `TwistStamped`, `behavior_server` → `Twist`,
  drei Publisher, einer je Verhalten), mit verschiedenen Type-Hashes
  (`RIHS01_9c45…` gegen `RIHS01_5f0f…`) — bei verschiedenem Hash bindet
  ROS 2 die Subscription gar nicht erst. Nachher trägt das Topic genau
  einen Typ, und ein direkt aufgerufenes `spin`-Goal dreht die Basis
  messbar um 96,0° (Yaw 1,6736 → −0,0021 rad, `SUCCEEDED`).

  **Gefunden hat es nicht diese Suite, sondern eine Foxglove-Warnung**
  („Multiple channels advertise the same topic … but the schema … do not
  match"). Der Grund für die Lücke ist strukturell: ohne Lidar hat die
  Costmap keine Hindernisse, also löst im Mock nie ein Recovery aus, und
  der tote Pfad wurde nie befahren. `test_every_cmd_vel_publisher_is_stamped`
  nagelt ihn jetzt statisch fest, über eine Liste aller Knoten, die selbst
  auf `cmd_vel` schreiben.

### Added
- Repo-Gerüst der Navigationsschicht.
- RS16-Treiberkonfiguration als **eine** Vorlage für Mock und Roboter;
  `husky_navigation.rslidar_config` rendert daraus die aufgelöste Fassung,
  Unterschied ist allein `common.msg_source`.
- `husky_navigation.wiring` als einzige Quelle für Topic- und Framenamen;
  die Launch-Dateien lesen sie, statt sie zu wiederholen.
- `lidar.launch.py` (Treiber + `pointcloud_to_laserscan`) — rein lesend.
- Nav2-Parametersatz, `navigation.launch.py` mit
  `localization:=none|amcl|slam` und eine synthetische Karte
  (`maps/leerer_raum.*`, erzeugt von `husky_navigation.make_map`).

  Stand: Nav2 fährt im Container-Mock gegen die Karte — `NavigateToPose`
  über 1 m endet mit `SUCCEEDED`, die EKF-Odometrie bestätigt die Strecke.
  **Ohne Lokalisierung und ohne Hindernisse**: `map→odom` liefert ein
  `static_transform_publisher`, AMCL und der `obstacle`-Layer brauchen
  Scans, und die gibt es erst mit einer RS16-Aufnahme.

  Am laufenden `controller_server` verifiziert: der Parameter heißt in
  dieser Nav2-Fassung `enable_stamped_cmd_vel` und steht auf `True`.
- `conftest.py` mit der Fixture `exclusive_base`: eine Dateisperre, die die
  fahrenden Tests serialisiert. Der Root-Lauf verteilt mit
  `-n 4 --dist loadfile` nach *Datei*, die beiden Fahrtests landeten also auf
  verschiedenen Workern und kommandierten dieselbe Basis — beide maßen die
  Bewegung des anderen und meldeten identische Zahlen.

  Zwei weitere Messfehler in denselben Tests behoben: das Ziel geht jetzt
  **zur Kartenmitte** (immer vorwärts trieb den Roboter aus der 10-m-Karte,
  Nav2 lehnte dann ab), und das Fahrfenster ist 8 s statt 3 s — `ros2 topic
  pub` braucht unter Last ein bis zwei Sekunden bis zum ersten Kommando, der
  Test maß die Anlaufzeit des CLI.
