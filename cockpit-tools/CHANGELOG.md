# Changelog

Format after [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning
after [Semantic Versioning](https://semver.org/).

## 2026-08-29 (the page speaks English)

- **The whole page is English -- the menu entry included.** `manifest.json` now carries the label
  `Robot tools`, `index.html` is `lang="en"` with English headings and hints, and every text
  `status.js` produces is English: `running`, `stopped`, `paused`, `restarting…`, `not created`,
  `broken (dead)`, `Docker unreachable`, `checking…`, plus the three VNC diagnosis notes. The operator on the robot sees
  English strings from now on; nothing about the logic, the codes (`no-password`, `bridge-network`, `desktop-down`) or
  the ball colors changed.
- **`node --test` states its expectations in the same words** (43 tests, unchanged in number), and the comments in
  `index.js`, `theme.js`, `style.css`, `install.sh` and the preview stub follow, with the transliterated umlauts written
  out of them.
- **The preview stub takes `&vnc=both` instead of `&vnc=beides`.**

## 2026-08-27 (Related pointed at a directory that is gone)

- **The link to `husky-offboard-lite` now names `husky-offboard`.** There is no
  `deploy/husky-offboard-lite/` any more: `lite` is a build stage of
  `deploy/husky-offboard`, deployed on the robot through `docker-compose.robot.yml`, and it is that stage which builds
  `husky-offboard-lite:jazzy` -- the container this page starts and stops. The old link resolved to nothing.

## 2026-08-25 (CI added)

- **`.github/workflows/ci.yml` added** -- `node --check` over every `.js`/`.mjs` file, `bash -n` over the two shell
  scripts and the package's own `npm test`, on push to `main` and on every pull request.
- **No install step and nothing fetched from npm.** `package.json` declares no dependencies, so a bare checkout runs the
  suite complete: 43 passed, 0 failed (2026-08-25 measured). Node 22 is the LTS line; the tests use nothing beyond
  `node:test` and `node:assert/strict`.
- **`node --check` is the counterpart of the ruff hard-error gate** the Python repos of this workspace run -- syntax
  errors only, no linter config to keep in step.
- **The shell check loops over the files.** `bash -n a b` checks only `a` and passes the rest to the script as its
  arguments.

## 2026-08-24 (README in English, skeleton aligned)

- **The README is now fully in English.** Per CLAUDE.md, `README.md` and
  `CHANGELOG.md` are English everywhere; a README is current state, so it was translated in one piece rather than
  paragraph by paragraph.
- **The README skeleton is aligned** to the workspace convention (`Features`,
  `Tech Stack`, `Installation`, `Usage`, `Running Tests`, `Related`,
  `Versioning`, `License`, with the package's own sections in between). This repo was the one documented outlier;
  CLAUDE.md asked for it to be brought into line the next time the file was touched.
- **The menu label stays `Roboter-Werkzeuge`** — it is the string in
  `manifest.json` that Cockpit shows, not prose. The internal link
  `#entwickeln` became `#development` along with its heading.
- Prose only, no behaviour change.

## [0.1.1] — 2026-08-24

### Geändert

- Die Seite trägt jetzt dasselbe Wurzel-Layout wie
  [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md): heller Seitengrund, darauf eine Wanne mit runden
  Ecken, links und rechts 1,5rem Abstand, oben bündig, unten dieselbe Luft — und sie scrollt selbst, damit die Ecken
  auch bei langem Inhalt stehenbleiben. Vorher lief der Inhalt randlos über den ganzen Rahmen, ohne Wanne und ohne
  Ecken.
- Farben, Abstände, Radien und Schriftgrößen kommen aus den PatternFly-6- Token, wie Cockpit sie ausliefert (am gebauten
  `index.css` des Nachbarn gemessen, Tokenname steht jeweils als Kommentar daneben). Die bisherigen Werte waren daneben:
  `#1b1d21` statt `#151515` als Grund, `#212427` statt
  `#292929` für die Karte.
- Karten und Knöpfe folgen den Radien von PatternFly 6 (16px bzw. Pille). Ein 6px-Kasten in einer 16px-Wanne war
  derselbe Bruch, nur kleiner.
- Fließtext (`.sub`, `.detail`, `.hints`) bleibt auf 46rem begrenzt, seit die Wanne die volle Breite hat.

### Behoben

- Das dunkle Thema hing an `prefers-color-scheme` und damit am Betriebssystem. Wer in Cockpit hell wählte, während der
  Rechner dunkel stand, bekam eine dunkle Seite zwischen lauter hellen. Neu ist `theme.js`:
  es liest `shell:style` aus dem localStorage, hört auf `storage` und
  `cockpit-style` und setzt `pf-v6-theme-dark` am `<html>` — dasselbe, was Cockpits eigenes `cockpit-dark-theme` in den
  anderen Paketen tut. Nur die Einstellung „auto" fragt weiterhin das System.

## [0.1.0] — 2026-08-20

### Hinzugefügt

- Erste Fassung: Cockpit-Seite „Roboter-Werkzeuge" mit einer Karte für den Container `offboard-lite-moveit-rviz-1` —
  Statuskugel, Starten, Stoppen.
- VNC-Karte mit `vnc://<rechner>:5900`, Kopierknopf und den Hinweisen zu Bildschirmfreigabe, `VNC_PASSWORD` (Vorgabe
  `husky`), RViz-Autostart und der Tatsache, dass *Execute* den echten Arm bewegt. Die Adresse kommt aus dem
  Cockpit-Aufruf, mit festem Rückfall auf `10.42.42.159`, wenn dort
  `localhost` steht.
- `install.sh` für `/usr/local/share/cockpit/robot-tools` (mit `--uninstall`).
- Der Container wird über `docker ps` am compose-Dienst und am Image gesucht statt über einen fest verdrahteten Namen —
  der hing am Verzeichnisnamen des Compose-Projekts und wäre bei jedem Umzug falsch geworden. Der gefundene Name steht
  in der Karte.
- Diagnose, warum Port 5900 nicht antwortet: der Desktop im Container ist gar nicht hochgekommen (gemessen von innen,
  erst nach dreimaliger Bestätigung — nach dem Start braucht er Sekunden), fehlendes `VNC_PASSWORD` (x11vnc bindet dann
  nur auf localhost) oder Bridge-Netz statt Host-Netz. Die letzten beiden entstehen beim Anlegen und überleben jedes
  `docker start`.
- `node --test` über die Zustandsabbildung in `status.js`.
