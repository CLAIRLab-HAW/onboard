# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.1.1] — 2026-08-24

### Geändert

- Die Seite trägt jetzt dasselbe Wurzel-Layout wie
  [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md): heller
  Seitengrund, darauf eine Wanne mit runden Ecken, links und rechts 1,5rem
  Abstand, oben bündig, unten dieselbe Luft — und sie scrollt selbst, damit
  die Ecken auch bei langem Inhalt stehenbleiben. Vorher lief der Inhalt
  randlos über den ganzen Rahmen, ohne Wanne und ohne Ecken.
- Farben, Abstände, Radien und Schriftgrößen kommen aus den PatternFly-6-
  Token, wie Cockpit sie ausliefert (am gebauten `index.css` des Nachbarn
  gemessen, Tokenname steht jeweils als Kommentar daneben). Die bisherigen
  Werte waren daneben: `#1b1d21` statt `#151515` als Grund, `#212427` statt
  `#292929` für die Karte.
- Karten und Knöpfe folgen den Radien von PatternFly 6 (16px bzw. Pille). Ein
  6px-Kasten in einer 16px-Wanne war derselbe Bruch, nur kleiner.
- Fließtext (`.sub`, `.detail`, `.hints`) bleibt auf 46rem begrenzt, seit die
  Wanne die volle Breite hat.

### Behoben

- Das dunkle Thema hing an `prefers-color-scheme` und damit am
  Betriebssystem. Wer in Cockpit hell wählte, während der Rechner dunkel
  stand, bekam eine dunkle Seite zwischen lauter hellen. Neu ist `theme.js`:
  es liest `shell:style` aus dem localStorage, hört auf `storage` und
  `cockpit-style` und setzt `pf-v6-theme-dark` am `<html>` — dasselbe, was
  Cockpits eigenes `cockpit-dark-theme` in den anderen Paketen tut. Nur die
  Einstellung „auto" fragt weiterhin das System.

## [0.1.0] — 2026-08-20

### Hinzugefügt

- Erste Fassung: Cockpit-Seite „Roboter-Werkzeuge" mit einer Karte für den
  Container `offboard-lite-moveit-rviz-1` — Statuskugel, Starten, Stoppen.
- VNC-Karte mit `vnc://<rechner>:5900`, Kopierknopf und den Hinweisen zu
  Bildschirmfreigabe, `VNC_PASSWORD` (Vorgabe `husky`), RViz-Autostart und der
  Tatsache, dass *Execute* den echten Arm bewegt. Die Adresse kommt aus dem
  Cockpit-Aufruf, mit festem Rückfall auf `10.42.42.159`, wenn dort
  `localhost` steht.
- `install.sh` für `/usr/local/share/cockpit/robot-tools` (mit `--uninstall`).
- Der Container wird über `docker ps` am compose-Dienst und am Image gesucht
  statt über einen fest verdrahteten Namen — der hing am Verzeichnisnamen des
  Compose-Projekts und wäre bei jedem Umzug falsch geworden. Der gefundene
  Name steht in der Karte.
- Diagnose, warum Port 5900 nicht antwortet: der Desktop im Container ist gar
  nicht hochgekommen (gemessen von innen, erst nach dreimaliger Bestätigung —
  nach dem Start braucht er Sekunden), fehlendes `VNC_PASSWORD` (x11vnc bindet
  dann nur auf localhost) oder Bridge-Netz statt Host-Netz. Die letzten beiden
  entstehen beim Anlegen und überleben jedes `docker start`.
- `node --test` über die Zustandsabbildung in `status.js`.
