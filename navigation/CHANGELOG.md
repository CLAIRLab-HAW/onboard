# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/),
Versionierung nach [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
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
