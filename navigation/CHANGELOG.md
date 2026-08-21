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
