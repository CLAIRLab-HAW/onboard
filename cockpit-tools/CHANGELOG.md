# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

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
- Diagnose, warum Port 5900 von außen nicht antwortet: fehlendes
  `VNC_PASSWORD` (x11vnc bindet dann nur auf localhost) oder Bridge-Netz statt
  Host-Netz. Beides entsteht beim Anlegen und überlebt jedes `docker start`.
- `node --test` über die Zustandsabbildung in `status.js`.
