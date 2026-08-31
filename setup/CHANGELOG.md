# Changelog — husky-custom-setup

What changed when. The current state is described in the [README](README.md).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
the versioning [Semantic Versioning](https://semver.org/).


## 2026-08-31 (the physics patcher carries a .py suffix like every other script here)

- **`scripts/urdf_physics_patch` is `scripts/urdf_physics_patch.py`.** It was the only Python file in this repo
  without the suffix; the convention is the other way round -- the suffix stays in the tree, and the installer
  drops it at the target (`octomap_feed.py` -> `octomap-feed`, `manipulator_diagnostics.py` ->
  `manipulator-diagnostics`). **The deployed name `/usr/local/bin/urdf-physics-patch` is unchanged**, so the boot
  service, the unit files and the running robot see nothing of this.
- **The test imports the tool by name.** `tests/test_urdf_physics_patch.py` built a `SourceFileLoader` by hand and
  put the module into `sys.modules` itself, because a suffix-less file cannot be imported. It is a plain
  `import urdf_physics_patch` now; the new `tests/conftest.py` puts `scripts/` on the path, which
  works under both import modes (the workspace root run uses `--import-mode=importlib`, CI's `pytest tests` the
  default one).
- **CI's syntax pass now reads the file at all.** `ruff check --select E9,F63,F7,F82 .` only ever looked at
  `*.py`, so the one script that got a `compile()` check in the installer was the one CI could not see. Both
  still run -- the installer's check is about a broken CHECKOUT, not about ruff -- but the comment claiming the
  check exists *because* the file has no suffix was wrong the moment it was written and is gone.
- **Until this is on `main`, an installer run WITHOUT a checkout finds no patcher.** `repo_file` falls back to
  raw.githubusercontent.com under the repo-relative path, and the old name is what stands there. It warns and
  leaves the existing `/usr/local/bin/urdf-physics-patch` in place (`repo_file`, not `require_repo_file`), so
  nothing breaks -- but a roll-out from `wget` alone would not pick up a new version of it before the push.

## 2026-08-31 (urdf_physics_patch survives a second run over a nested element)

- **`apply_target` recognises a property element that has children.** The anchor for an existing element was
  `<child\b.*?(?:/>|</child>)`, and non-greedy `.*?` stops at the FIRST `/>` -- which inside an `<inertial>` is
  its own `<origin/>`. The pattern now carries the alternation one level up, `<child\b(?:[^>]*/>|[^>]*>.*?</child>)`,
  so the self-closing form is tried first and the closing-tag branch spans the whole element.
- **What it cost:** a second run over an already-patched `<inertial>` matched 33 of the fragment's 141 characters,
  reported `refreshed`, and built a block with a mismatched tag. The well-formedness gate refused to write it and
  logged ERROR, so no description was ever broken -- but the tool was not idempotent for exactly the `top_plate`
  target it anticipates, and a per-boot patcher that reports a change every boot is one nobody can read the log of.
  `<dynamics>` was unaffected throughout: it is self-closing, and the first `/>` is its own.
- **`tests/test_urdf_physics_patch.py` applies a nested `<inertial>` twice** and asserts the second action is
  `unchanged` -- the case the suite's other idempotency test (`ur_macro.xacro`'s `<dynamics>`) could not reach.

## 2026-08-31 (the gripper node leaves, its service stays)

- **`scripts/rg6_grip_bridge.py` and `scripts/rg6_finger_kinematics.json` moved to `onrobot-rg6`**
  (`rg6_control/scripts/`). The bridge is the driver half of the gripper, and its mock half `rg6_control_sim` was
  in that package all along -- same action, same `bridge_state` fields, same table. It stood here because the
  systemd unit did, which is a deployment reason and not an ownership one.
- **The unit, the wrapper and the root-owned copy stay.** `clearpath-custom-rg6-grip-bridge` is unchanged;
  `ExecStart` still points at `/usr/local/bin/rg6-grip-bridge`. Only the SOURCE of that copy changed, from
  `repo_file` to `rg6_tool_src` -- the resolver that already fetched `rg6_moveit_patch` out of the rg6 workspace.
- **`--verify` follows.** The two files left the repo manifest and joined the three-file loop over the rg6-sourced
  tools, so a deployed copy is still hashed against the source it came from.
- **`tools/rg6_stroke_survey.py` imports the bridge from where it now lives.** Three candidates instead of one
  hard-coded `../scripts`: the workspace checkout, the robot's clone and its install space. Not found means an
  error naming all three, rather than an `ImportError` on a path nobody stated.
- **CI drops the `onrobot-rg6` checkout and the linkage step.** This repo is the single source of truth for
  `robot.yaml` alone now; the table's two parity guards sit in repos that are not this one, so a change here
  cannot break them. Its own `tests/` run in that place instead.

## 2026-08-31 (robot.yaml lists a second workspace)

- **`platform.extras.urdf.path` points into the new repo `husky-extras`.** The extras file (sensor arch, ArUco
  marker, and where the RG6 is bolted onto the UR5 flange) sat in `rg6_description`, a package that describes a
  gripper -- while every link in it names a frame of THIS robot (`arm_0_tool0`, `top_plate_rear_mount`,
  `top_plate_front_mount`).
- **`system.ros2.workspaces` therefore carries two entries now.** Both are needed together, and it is worth being
  precise about why: the generator finds the extras file by its absolute path, but expands
  `$(find rg6_description)` and `package://husky_extras_description` through the ament index that these workspaces
  build up. A missing rg6 overlay kills the generator run on the include; a missing extras overlay leaves the arch
  without a mesh in RViz and Foxglove.
- **The installer clones and builds the second workspace as well**, next to the rg6 one and after it. A failing
  clone warns rather than aborting, and says what it costs: a URDF without the arch, the marker and the gripper.
- **Sequence matters when this reaches the robot.** `/etc/clearpath/robot.yaml` is a symlink into the checkout, so
  a `git pull` here takes effect at once -- while `husky-extras` is only there after an installer run. Pulling
  this repo without running the installer generates a robot without extras at the next boot. R49 carries the
  roll-out.

## 2026-08-31 (physical properties into the descriptions the generator reads)

- **New `scripts/urdf_physics_patch`.** Puts physical properties into the apt descriptions that ship without
  them: the six UR joints' `<dynamics damping="0" friction="0"/>`, the four wheel joints without any, and
  `top_plate_link` with a collision mesh and no `<inertial>`. None of the three has a lever in `robot.yaml` --
  `clearpath_config` does not model joint dynamics, and both descriptions come from apt.
- **It patches the package macros, not a generated file, and that decides the design.** There is no
  `/clearpath/robot.urdf` to append to -- only a 2.5 kB `robot.urdf.xacro` wrapper expanded at launch -- and an
  existing joint's dynamics cannot be overridden by declaring it twice. So the edit lands IN the macro,
  idempotent, with a `.bak` and an atomic write, the same shape as the two package edits
  `clearpath_custom_setup.py` already makes.
- **All nine targets ship without a value, on purpose.** Nobody has measured the viscous damping or the Coulomb
  friction of this arm, and `maniskill_robot.physics.ARM_DAMPING = 100.0` is not that number: it is the D gain of
  a PD drive, where `<dynamics damping>` is passive drag in the joint. Writing the one into the other adds
  100 N*m*s/rad underneath a drive tuned without it. R47 carries the measurement; the tool names each missing
  value and changes nothing.
- **`clearpath_custom_setup.py` gained step 5, `run_urdf_physics_patch`.** Delegates to the root-owned copy under
  `/usr/local/bin`, the same arrangement as step 4 and for the same reason: the service runs as root and must not
  call anything out of a user-writable checkout.
- **Numbered last, runs first.** Step 4 edits what the Clearpath generator writes (the flat `robot.srdf`); step 5
  edits what it reads (`ur_macro.xacro`, the a200 wheel and top plate macros). Both windows are inside this
  service, and the ordering is the whole of it.
- **The installer deploys it like every other script here** -- `repo_file`, compile check, root-owned copy, and an
  entry in the `--verify` manifest. New `URDF_PHYSICS_PATCH_BIN` under `/usr/local/bin`. `rg6_tool_src` stays, but
  for `rg6_moveit_patch` alone: that one really does come from a foreign workspace, and the one-element loops the
  shared arrangement left behind are gone.
- **New `tests/`, the first pytest suite in this repo.** 17 tests for the patcher, run from the workspace root
  without ROS and without a robot. They edit COPIES of the real upstream files where the workspace bundle has
  them -- the point is not that the tool can edit some XML, it is that it can edit `ur_macro.xacro` as UR writes
  it -- and skip themselves by name in a bare checkout.

## 2026-08-30 (the inert BLE001 directives are gone)

- `# noqa: BLE001` removed in 1 place. `BLE` is not in the workspace lint scope, so these directives suppressed
  nothing -- they were flake8 residue. Where one carried a justification, the justification stays as a plain comment.
- Enabling the rule instead was measured and rejected: 156 blind `except Exception` stand in the workspace against 88
  directives, so the marker was never a reliable signal, and switching it on would have produced 87 findings.

## 2026-08-30 (ruff resolves the same settings from anywhere)

- **CI pins `ruff>=0.16.5,<0.17`** -- the minor the lint scope was measured against, the same bound the
  workspace dev group carries. Unpinned, a ruff release can stabilise new rules and turn this CI red without
  a commit of ours.

## 2026-08-30 (the silent paths on the robot speak, without lying on the topic)

- **`rg6_grip_bridge` reports a status outage edge-triggered.** The TOPIC stays silent on purpose -- the silence
  is itself the signal, and the diagnostics judges the age of the last status from it. The LOG is a different
  channel and lies to nobody: one WARNING when the outage begins, one INFO with its duration when it ends. Per
  iteration it would have buried the moment it began under thousands of identical lines at
  `joint_state_rate_hz`.
- **`clearpath_custom_setup` says which file it could not patch.** An unreadable file was skipped in silence
  while the run still reported success for the files it did reach; a failed `.bak` was equally quiet, and the
  patch that follows it cannot be undone.
- **`octomap_feed` reports the dropped frame on a size mismatch**, throttled, exactly as the sibling branch above
  it already did for an unknown encoding -- a mismatch previously looked like no frames arriving at all.
- **`rg6_stroke_survey` notes a settle or read-back failure on stderr**, like the grip failure already did:
  stdout carries the survey, and a run that quietly drops half its points looks like a complete one.
- Checked and deliberately left silent: the five handlers in `manipulator_diagnostics` (three store the import
  error and report it later, one must not raise inside a callback, one is the normal stop) and the `Rg6Client`
  self-test assertions.

## 2026-08-29 (the parity guards fire when THIS repo changes)

- **`.github/workflows/ci.yml`** runs the two suites that read this repo as their source of truth: the linkage
  parity in `onrobot-rg6` (60 tests) and the SSOT and gripper-linkage parity in `robot-contract` (15). Both guards
  live in the other repos, so until now they only ever fired when one of *those* was touched -- a change to
  `config/robot.yaml` or `scripts/rg6_finger_kinematics.json` here went unnoticed until someone happened to edit
  the far side. Measured in a bare 3.11 venv: 75 tests, 1.7 s, no ROS and no robot.
- **`touch workspace.repos` is load-bearing in that workflow.** Both suites walk up for the marker and skip by name
  while there is none; without it the run would be green having compared nothing.
- **The scripts get a syntax pass instead of a suite** -- `ruff --select E9,F63,F7,F82` for Python (importing them
  needs rclpy, which no runner has) and `bash -n` over every `*.sh`.

## 2026-08-27 (the Cockpit page "Roboter-Werkzeuge" joins the installer)

- **The installer deploys `cockpit-robot-tools` as well**, as an optional step
  next to the `cockpit-ros2-diagnostics` fork: clone or `git pull` into
  `~/cockpit-robot-tools`, then run the page's own `install.sh`. The step is
  the cheaper of the two Cockpit blocks -- static files, so it never asks for
  `npm`/`make` on the robot and has no "build it elsewhere and bring the result
  over" fallback. Root comes from the installer, which is what the manual route
  lacked: on the robot `sudo` wants a password, so the rollout could not be
  driven from a non-interactive session.
- **The copy step is the page's `install.sh`, not a second `cp`.** Which files
  belong in the package is decided by its `FILES=(...)`; repeating that list in
  the installer would be a second truth about the very thing this change exists
  to keep in step.
- **`--verify` measures the page**, file by file, reading the same `FILES=(...)`
  out of `install.sh`. It reports `NOT-DEPLOYED`, `SOURCE-MISSING`, `DEVIATION`
  (naming the files) or `OK` like every other entry, and an unreadable file list
  counts as `SOURCE-MISSING` rather than passing quietly. The two candidate
  source paths are the sibling checkout (`../cockpit-robot-tools`, the workspace
  layout) and `~/cockpit-robot-tools` (the robot, where both coincide).
- **`CRT_PREFIX` is handed to that `install.sh`**, and `CRT_PKG_DIR` derives from
  it -- so the directory the installer writes and the directory `--verify`
  measures are one value instead of two that happen to agree.
- A directory without `.git` -- how the page reached the robot before this
  existed, by `rsync` -- is installed, but says out loud that nothing keeps it
  current.

## 2026-08-27 (tools/ next to scripts/ and config/)

- **`wakeup.sh`, `shutdown.sh`, `ur-calibrate.sh` and `rg6_stroke_survey.py`
  moved to `tools/`.** The boundary is not a matter of taste: `scripts/` is what
  the installer deploys -- exactly the `--verify` manifest -- and `tools/` is
  what a human starts against the robot. Both halves were already there, they
  just shared a directory, and nothing said which was which.
- **`rg6_stroke_survey.py` says its cross-directory import out loud.** It needs
  `rg6_grip_bridge` from `scripts/`; Python resolves a sibling import against
  the script's own directory, so the dependency is now a `sys.path` line with
  the reason next to it instead of an accident of the layout. The deployed copy
  cannot serve it either -- `/usr/local/bin/rg6-grip-bridge` has hyphens and no
  `.py`, so it is not importable.
- The three remote search paths of the SSH wrappers in the workspace root learn
  `tools/`; they keep the old ones, so a robot that has not pulled yet still
  answers.

## 2026-08-27 (config/ next to scripts/)

- **`robot.yaml`, `ur5_a200_0553_calibration.yaml` and
  `rtde_input_recipe_no_tool.txt` moved to `config/`.** The repo now separates
  what this robot RUNS ON (`config/`) from the code that gets deployed
  (`scripts/`), with the installer on top tying them together.
- **The symlink target changed with them**: `/etc/clearpath/robot.yaml` now
  points at `config/robot.yaml`. The installer names the target once
  (`ROBOT_YAML_REL`) instead of spelling the path in seven places, and it
  reports a dangling symlink out loud before repairing it rather than healing it
  in silence -- a `git pull` that moves the file leaves the Clearpath stack
  without its config until the installer runs, and that should be visible.
- Two consumers outside this repo follow in their own commits:
  `deploy/husky-offboard/entrypoint.sh` fetches both YAMLs by URL from main, and
  `contract/robot-contract/tests/test_ssot_parity.py` reads the SSOT path.

## 2026-08-27 (require_repo_file: the call form is load-bearing)

- **`require_repo_file` must be called as an assignment.** Its `exit 1` leaves
  the command substitution's subshell, not the installer; what stops the run is
  `set -e` picking up the failed assignment. As an argument to another command
  only that command's status counts, the empty string travels on and the run
  continues past the error. Both forms measured side by side on 2026-08-27; the
  rule is written at the function, because the wrong form looks identical.
- The error message no longer claims GitHub was unreachable when it answered
  404 -- it names both readings, including "the file is not on main yet".

## 2026-08-27 (the watchdog is a file, not a heredoc)

- **`scripts/manipulators_watchdog.sh` is a real file**, deployed through
  `require_repo_file` with a `bash -n` check before it lands, and hashed by
  `--verify`. 232 lines of shell inside a quoted heredoc could not be read by
  `bash -n`, by shellcheck or by an editor -- the recovery logic that restarts
  the arm driver was the least inspectable code in the repo.
- With the patcher gone the same way, `install-clearpath-custom-setup.sh` is
  down from 1950 to 1463 lines, and the share of it that is foreign code inside
  strings from 39% to 19% (289 of 1463 lines) -- all of that now unit files and
  wrappers that interpolate installer variables, which is where a heredoc
  belongs.

## 2026-08-27 (the config patcher is a file, not a heredoc)

- **`scripts/clearpath_custom_setup.py` is a real file.** 249 lines of Python
  lived inside a quoted heredoc in the installer, where no editor, syntax check
  or test could see them -- while the four other artefacts the installer
  deploys have come out of `scripts/` through `repo_file` all along. The
  patcher now takes the same route: resolve, compile check, self-test,
  root-owned copy, and `--verify` hashes it like the rest.
- **It is fetched with `require_repo_file`**, not `repo_file`: it is the
  `ExecStart` of the boot service, so a missing source has to stop the run.
- **`--selftest` is new** and exercises the two patterns off the robot: that the
  arm JSB remap hits `'platform','joint_states'` exactly once, leaves
  `'platform','dynamic_joint_states'` alone, is idempotent and does not care
  about quoting or spacing; and that the mesh URI swap spares a foreign package.
  Both patterns moved to module level (`ARM_JS_RX`, `MESH_URI_OLD`) so the test
  exercises the real ones instead of a copy that drifts.
- The file is formatted with black now that it is a file -- so the first
  `--verify` after this change reports DEVIATION against the copy on the robot
  until the installer runs once.

## 2026-08-27 (the repo checkout comes first, and repo_file accepts wget)

- **The `robot.yaml` clone runs before everything else.** `repo_file` resolves
  against `${SETUP_WS}`, so every artefact the installer deploys is answered
  from that checkout -- ahead of the clone only "next to the script" or the
  network could answer, and a `wget` of the single installer file has no "next
  to the script". The symlink step travels with it, they were always one block.
- **`repo_file` takes `wget` when there is no `curl`.** The documented install
  path is a `wget` of one file, so a machine with wget and without curl is
  exactly the machine that reaches this code; insisting on curl made the
  resolution fail there without a word.
- **`require_repo_file` is new**: for a file the installer cannot do without, it
  aborts with the three places it looked and what to do, instead of leaving a
  systemd unit behind that has no `ExecStart`.

## 2026-08-27 (the UR calibration leaves the installer)

- **`scripts/ur-calibrate.sh` is new; the installer no longer offers the UR
  kinematics calibration.** It was the only step that ran `apt-get install`, and
  it ran it on the whole UR stack (`ur-client-library`, `ur-robot-driver`,
  `ur-calibration` can only be installed together, the `ur_calibration` ABI has
  to match) on a robot whose UR stack is pinned on purpose. The question sat
  behind a `[y/N]`, which `-y` answers with yes -- so
  `install-clearpath-custom-setup.sh -y` lifted the arm's version protection
  without anyone seeing it. It also needs a powered arm and writes a file that
  has to be entered in `robot.yaml` by hand: a measurement procedure, not an
  installation step.
- **The installer now installs no package at all** -- it writes files and
  systemd units. The two remaining apt mentions are read-only `dpkg -s` checks
  and one line of advice.
- The new script takes `--robot-ip`, `--out` and `--skip-apt`, keeps the five
  newest backups of a previous measurement, and skips the sudo round trip when
  it already runs as the target user (this robot has no passwordless sudo).

## 2026-08-27 (installer prose audited against what the script does)

- **The header list was seven entries short.** `clearpath-custom-joint-states`,
  the sysctl reservation of the UR ports, the RTDE recipe and the root-owned
  `rg6_moveit_patch` copy are installed unconditionally and were not named at
  all; the octomap feed, the manipulator diagnostics and the Cockpit fork were
  missing among the optional ones. The list now follows the order the installer
  actually works in, and the closing summary names the sysctl file and the RTDE
  recipe too.
- **Three R-references pointed into ROBOTER-TODO.md, where they no longer are.**
  R6, R22 and R25 are closed and live in the archive; the pointers say so.
- **`rg6_msgs` was described as deliberately left out of the colcon build.** The
  package does not exist any more, so there is nothing to leave out -- the
  comment now says the workspace has no interface package. Same for the wrapper
  comment of the manipulator diagnostics.
- **The `--verify` guard comment no longer explains itself through the past.**
  It says why robot.yaml is a good guard, not what stopped being one.
- The invocation block no longer asks for an `RG6_REPO_URL` that has been set
  for a long time; the patcher docstring says why its list starts at 2; one
  German output line ("oder reboot") became English.
- Comments and one echo line only, no behaviour change.

## 2026-08-27 (installer comments: allowlist is a robot.yaml lever, not a patch)

- **The header and the unit-file comment no longer list the foxglove
  `asset_uri_allowlist` among what the per-boot patcher writes.** It is set in
  `robot.yaml` under `platform.extras.ros_parameters.foxglove_bridge`; the
  patcher's own `main()` has said so since 0.2.0, only these two spots still
  claimed the old way. The ordering note on
  `Before=clearpath-platform.service` now names the reason that still holds:
  the patched sensor meshes.
- Comments only, no behaviour change.

## 2026-08-24 (.gitignore normalised to the workspace base)

- **`.gitignore` now uses the workspace's lean 8-line base** (`__pycache__/`, `*.py[cod]`, `*.egg-info/`, `build/`, `dist/`, `.venv/`, `.pytest_cache/`, `.DS_Store`). No package-specific extras.

## 2026-08-24 (README in English)

- **The README is now fully in English.** Per CLAUDE.md, `README.md` and
  `CHANGELOG.md` are English everywhere; a README is current state, so it was
  translated in one piece rather than paragraph by paragraph.
- **What Cockpit displays stays verbatim.** The power-off check still names the
  tile text `Außer Betrieb`, because the plugin fork is translated into German
  and that is what an operator sees on screen.
- Prose only, no behaviour change — no unit, script or parameter was touched.

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

- **`rg6_finger_kinematics.json` regenerated against the clamped gripper model.** The table now starts at
  `q = 0.038` rad / 151,13 mm instead of `q = 0.0` / 153,17 mm: measured on 2026-08-27 at the robot, the mechanical
  open stop is 151,10 mm wide and the four-bar chain never reaches its geometric zero. Generated file, not
  maintained -- the change belongs to `onrobot-rg6` (`rg6_v2.yaml`, `tools/derive_finger_kinematics.py`); the copy
  here is what `rg6_grip_bridge` reads on the robot.

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
