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
