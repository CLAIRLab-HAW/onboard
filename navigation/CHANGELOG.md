# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/),
Versionierung nach [SemVer](https://semver.org/).

## [Unreleased]

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
