# cockpit-robot-tools

Eine Cockpit-Seite für wiederkehrende Handgriffe am Roboter. Zurzeit enthält
sie genau eine Karte: den **Offboard-Lite-Container** starten und stoppen, mit
Statuskugel und der Adresse, unter der man dem Container per VNC zusieht.

Der Name ist absichtlich offen gehalten — weitere Karten (andere Container,
andere Handgriffe) kommen hier dazu, ohne dass das Paket umgetauft werden muss.

![Die Seite in der Vorschau](screenshots/vorschau.jpg)

*(Cockpit → „Roboter-Werkzeuge"; hier in der Vorschau am Arbeitsplatz, siehe
[Entwickeln](#entwickeln).)*

## Was die Seite tut

**Statuskugel.** Alle drei Sekunden ein
`docker inspect -f '{{.State.Status}}' offboard-lite-moveit-rviz-1`. Im
Hintergrundtab wird nicht abgefragt.

| Kugel | Bedeutung |
|---|---|
| grün | `running` — der Container läuft |
| grau | `exited` / `created` / `paused` — **gestoppt, das ist der Normalfall** |
| gelb, pulsierend | Start oder Stopp unterwegs, oder `restarting` |
| grau, hohl | Der Container ist auf diesem Rechner gar nicht angelegt |
| rot | Docker antwortet nicht, keine Rechte, oder Container `dead` |

Gestoppt ist bewusst **grau und nicht rot**: sonst leuchtete die Kugel die
meiste Zeit alarmierend, obwohl nichts kaputt ist — und ein echter Fehler ginge
darin unter.

**Starten / Stoppen.** `docker start` bzw. `docker stop` auf den vorhandenen
Container. Die Seite legt **keinen** Container an und ruft **kein** `compose`
auf; fehlt der Container, sagt sie das und nennt den einmaligen Befehl dafür.
Der jeweils sinnlose Knopf ist ausgegraut (kein `start` auf einen laufenden
Container, kein `stop` auf einen gestoppten).

**VNC.** Die Adresse `vnc://<dieser-rechner>:5900` als Link und zum Kopieren,
dazu die Hinweise, die man dort braucht: wie man sie am Mac öffnet, dass der
Viewer nach dem `VNC_PASSWORD` des Containers fragt (Vorgabe `husky`, 8 Zeichen
Protokollgrenze), dass **RViz mit dem Container hochkommt**
(`RVIZ_AUTOSTART=1`) und im `xterm` mit `moveit-rviz` neu startbar ist — und
dass *Execute* den echten Arm bewegt.

Der Rechnername kommt aus der Adresse, unter der Cockpit geöffnet wurde (über
einen Cockpit-Sprungrechner aus `cockpit.transport.host`). Steht dort
`localhost` oder `127.0.0.1` — Cockpit direkt auf dem Roboter oder durch einen
SSH-Tunnel geöffnet —, wäre das als VNC-Ziel der falsche Rechner; dann greift
der feste Rückfall `ROBOT_HOST` in `index.js`, zurzeit `10.42.42.159`. Ein
anderes Netz (netbird) trägt man dort ein.

## Voraussetzungen auf dem Roboter

- **Der Container muss einmal angelegt worden sein**, üblicherweise mit
  ```bash
  cd ~/offboard-lite
  docker compose -f docker-compose.yml -f docker-compose.robot.yml up -d
  ```
  Danach genügt für alles Weitere diese Seite.
- **Admin-Zugang in Cockpit.** Die Docker-Aufrufe laufen mit
  `superuser: "require"`. Wer sich in Cockpit nicht als Administrator
  freigeschaltet hat, sieht eine rote Kugel mit der Fehlermeldung.
- **Docker im PATH.** Auf a200-0553 ist Docker das *snap*-Docker; die Seite
  stellt deshalb `/snap/bin` vor den PATH, bevor sie `docker` aufruft.

## Installation

Kein Build. Das Paket ist reines Vanilla-JS gegen `cockpit.js` und wird so,
wie es hier liegt, kopiert — auf dem Roboter braucht es weder node noch npm.

```bash
# vom Arbeitsplatz aus:
rsync -a robot/cockpit-robot-tools/ robot@10.42.42.159:~/cockpit-robot-tools/
ssh robot@10.42.42.159 'sudo ~/cockpit-robot-tools/install.sh'
```

Ziel ist `/usr/local/share/cockpit/robot-tools` — dieselbe Ebene wie der
[cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md)-Fork; die
beiden Pakete stören einander nicht. Danach im Browser auf
`http://<robot>:9090` neu laden, der Menüpunkt heißt **Roboter-Werkzeuge**.

Rückbau: `sudo ~/cockpit-robot-tools/install.sh --uninstall`.

## Entwickeln

```bash
node --test test/*.test.mjs     # Zustandsabbildung (status.js)
```

`status.js` ist die einzige Datei mit Entscheidungslogik und deshalb die
einzige mit Tests: welche Farbe, welcher Text, welcher Knopf aktiv. Der Rest
von `index.js` ist DOM und `cockpit.spawn`.

Die Seite lässt sich ohne Roboter ansehen, indem man ein `cockpit.js`-Attrappe
danebenlegt (siehe `test/preview/`) und das Verzeichnis mit einem beliebigen
statischen Server ausliefert.

## Sicherheitshinweis

Der VNC-Port hat inzwischen ein Passwort (`VNC_PASSWORD`, Vorgabe `husky`);
VNC-Passwörter sind protokollbedingt auf 8 Zeichen begrenzt, das ist eine Hürde
und kein Schutz. Bei `network_mode: host` liegt Port 5900/6080 direkt auf der
Roboter-IP, und aus dem Desktop heraus ist der echte Arm über MoveIt bedienbar.
Diese Seite macht das Starten bequem — die Abwägung bleibt dieselbe
(R3 in [ROBOTER-TODO.md](../../ROBOTER-TODO.md)): nur in einem
vertrauenswürdigen Netz starten und danach wieder stoppen.

## Verwandt

- [husky-offboard-lite](../../deploy/husky-offboard-lite/README.md) — der Container, den diese Seite bedient
- [cockpit-ros2-diagnostics](../cockpit-ros2-diagnostics/README.md) — das Diagnose-Plugin daneben

## Versionierung

[Semantic Versioning](https://semver.org/) über `VERSION` und [CHANGELOG.md](CHANGELOG.md).

## Lizenz

Siehe Workspace-Wurzel.
