# husky-navigation

Navigationsschicht des Husky **a200-0553**: der Sensorpfad des RoboSense
RS-LiDAR-16 und Nav2. Läuft im husky-offboard-Container gegen die
Mock-Plattform **und** onboard am echten Roboter — dieselbe Konfiguration,
derselbe Treiber.

## Features

- **Ein Treiber für beide Seiten.** `rslidar_sdk` (apt, `ros-jazzy-rslidar-sdk`)
  liest im Mock eine PCAP-Aufnahme und am Roboter das Gerät. Unterschied:
  `common.msg_source`.
- **Nav2** mit umschaltbarer Lokalisierung: `slam_toolbox` zum Kartieren,
  AMCL zum Fahren gegen eine gespeicherte Karte.
- **ROS-freier Kern.** Die Entscheidungen liegen in `src/husky_navigation/`
  und sind ohne ROS testbar; die Launch-Dateien importieren sie.

## Stand

**Nav2 fährt im Container-Mock gegen eine synthetische Karte.** Belegt, nicht
behauptet: ein `NavigateToPose` über 1 m endet mit `SUCCEEDED`, und die
EKF-Odometrie vorher/nachher bestätigt die Strecke.

**Der Sensorpfad ist gebaut und konfiguriert, aber ungefahren.** Es fehlt die
RS16-Aufnahme (R-Punkt in `ROBOTER-TODO.md`); die zugehörigen Tests
überspringen sich mit benannter Ursache. Bis dahin gilt:

- `map→odom` liefert ein `static_transform_publisher` (Identität), nicht AMCL.
  Ein AMCL ohne Scans publiziert *gar keine* Transformation.
- Die Lokalisierung trägt allein die Radodometrie — der Roboter driftet gegen
  die Karte.
- Die Costmap hat **keine** Hindernisse.

Der Satz lautet also nicht „Nav2 läuft", sondern: *Nav2 fährt im Mock gegen
eine Karte; die Sensorkette wartet auf eine Aufnahme.*

## Frames — der Roboter steckt im Boden, und das ist keiner

In RViz und Foxglove steht der Husky sichtbar **13,2 cm unter** der
Bodenebene der Karte. Das sieht nach einem kaputten URDF aus und ist keins:

```
base_link → base_footprint    z = −0,13228     (URDF)
Radachse  → base_link         z = +0,03282     (URDF)
Radradius                         0,1651       (control.yaml)
                              0,03282 − 0,1651 = −0,13228   ✓ exakt
odom      → base_link         z =  0,000       (EKF)
map       → base_footprint    z = −0,132       ← daher
```

`base_footprint` ist also **korrekt** definiert — genau dort, wo die Räder
den Boden berühren. Der Versatz entsteht eine Ebene höher: der EKF läuft mit
`base_link_frame: base_link` und `two_d_mode: True` und pinnt damit
`base_link` auf z = 0 der Odometrie-Ebene, obwohl base_link im URDF 13,2 cm
über dem Boden sitzt.

Das ist Clearpaths Konvention aus der generierten `localization.yaml`. Über
`robot.yaml` ist sie nicht einstellbar (dort steht nur `enable_ekf: true`),
und die generierte Datei zu patchen wäre genau die Driftquelle, die der
Workspace vermeidet. **Für Nav2 ist es folgenlos** — dort zählen x, y und
yaw.

Zwei Stellen, an denen es doch zählt:

- **Höhenbänder rechnen ab `base_link`, nicht ab dem Boden.**
  `pointcloud_to_laserscan` filtert mit `min_height: -0.10`; das sind 3,2 cm
  über dem Boden, nicht 10 cm darunter. Steht in
  `husky_navigation.wiring` mit dieser Rechnung dabei.
- **Eine Bodenebene als Kollisionsobjekt bei `map` z = 0 läge 13,2 cm zu
  hoch** — mitten im Roboter. Wer für den Arm eine einzieht, setzt sie auf
  `base_footprint`.

`test_the_ground_frame_matches_the_wheel_geometry` nagelt die URDF-Seite
fest: Es prüft, dass `base_footprint` zur Radachse **und** zum
`wheel_radius` aus `control.yaml` passt. Beide Quellen wissen nichts
voneinander; laufen sie auseinander (etwa beim Wechsel auf Outdoor-Räder),
ist nicht nur die Darstellung falsch, sondern auch die Odometrie — und das
meldet niemand. Ob der Radius zur *realen* Drehung passt, kann der Mock
prinzipiell nicht prüfen: siehe R37.

## Tech Stack

ROS 2 Jazzy · `rslidar_sdk` · `nav2` · `slam_toolbox` ·
`pointcloud_to_laserscan` · Python 3.11+

## Installation

Teil des clearpath-uv-Workspace (`uv sync` am Root). Ins Offboard-Image kommt
das Repo über `additional_contexts` beim `docker compose build`.

## Usage

Siehe `deploy/husky-offboard/scripts/nav` im Container.

## Running Tests

```bash
uv run pytest robot/husky-navigation          # ohne ROS, ohne Container
uv run pytest -m nav_e2e                      # braucht laufenden Container
```

## Related

- [Design-Spec](../../docs/superpowers/specs/2026-08-22-nav2-rs16-design.md)
- [robot-contract-Profil](../../contract/robot-contract/src/robot_contract/profiles/a200_0553.yaml)

## Versioning

[SemVer](https://semver.org/), Historie im [CHANGELOG](CHANGELOG.md).

## License

Siehe Workspace.
