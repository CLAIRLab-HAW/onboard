# Changelog — onboard

What changed in this repository as a whole. Each package keeps its own history in its own `CHANGELOG.md`
next to its README, and those entries are not repeated here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), the
versioning [Semantic Versioning](https://semver.org/).

## 2026-09-03 (following the E2E marker rename)

- **`mock_e2e`, `offboard_e2e`, `nav_e2e`, `maniskill_e2e` are `e2e_mock`, `e2e_container`, `e2e_container_nav`,
  `e2e_container_maniskill`** — the markers spell the stage token (C2 of the naming plan, root `pyproject.toml`).
  Marks, the member `pyproject.toml` registrations and the prose follow; no test moved and no behavior changed.

## 2026-09-03 (following the motion protocol rename)

- **`/twin/*` is `/motion/*` and `twin_protocol` is `clair.robot.contract.motion`.** Imports, topic names and the
  `MOTION_DIRECT_EXECUTE` / `MOTION_SOURCE` variables follow the contract, which carries the `PROTOCOL_VERSION`
  bump from 9 to 10. No behavior changed here.

## [1.0.0] - 2026-09-03

The repository comes into being out of seven, and the subdirectories drop the platform from their names --
nothing here needed to say "husky" twice:

| Was | Is | Commits |
|---|---|---|
| `onboard/husky-custom-setup` | `setup/` | 134 |
| `onboard/husky-extras` | `extras/` | 5 |
| `onboard/onrobot-rg6` | `rg6/` | 107 |
| `onboard/ur-state-manager` | `ur-state/` | 42 |
| `onboard/husky-navigation` | `navigation/` | 45 |
| `onboard/cockpit-ros2-diagnostics` | `cockpit-diagnostics/` | 51 |
| `onboard/cockpit-robot-tools` | `cockpit-tools/` | 13 |

- **One branch was NOT merged, and is kept as one.** `onrobot-rg6` carried `fix/rg6-mimic-preview` with a
  commit of 2026-07-10 that `main` does not have ("Fix mimic behavior in viz": the MoveIt patch, the
  joint-state broadcaster and two xacros). Merging only `main` would have dropped it silently, and whether it
  belongs in `main` is not a question a consolidation script may answer. It is
  `absorbed/rg6/fix/rg6-mimic-preview` here, unmerged and reachable.
- **The histories came along whole**, through `git filter-repo --to-subdirectory-filter` before each merge.
- **`/home/robot/` was left alone.** The 16 references to the robot user's home in `robot.yaml`,
  `urdf/generate.sh`, the ament setup scripts and four READMEs name paths ON the machine, not in this
  workspace. Pulling them along would have broken the boot path.
- **What the robot has to catch up on is R57**, not this entry: the seven checkouts under `/home/robot/`
  become one, and `robot.yaml`, the installer and the two Cockpit plugin paths follow when the owner rolls it
  out.
