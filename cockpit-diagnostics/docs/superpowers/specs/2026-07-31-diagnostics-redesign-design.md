# Redesign des Cockpit-Diagnosepanels

Stand: 2026-07-31 · Fork `robot/cockpit-ros2-diagnostics`

## Ziel

Die Seite soll technisch eleganter wirken, **ohne dass Information verloren geht**.
Kein Feld, kein Wert und kein Status verschwindet; sie werden anders angeordnet
und anders kodiert. Dazu kommen vier funktionale Ergänzungen (Suche, Level-Filter,
zusammengeführte Auffälligkeitenliste, Zeitachse) und der Umzug des Diagnose-Captures
in ein Menü.

Der Fork geht seinen eigenen Weg: bestehende Upstream-Dateien dürfen frei umgebaut
werden. Ein späterer Rebase auf eine neue Clearpath-Version ist Handarbeit — was er
faktisch heute schon ist, weil der Fork das apt-Paket über `/usr/local/share/cockpit`
ohnehin überdeckt.

## Entwurfsgrundsätze

Drei Regeln, aus denen sich der Rest ableitet:

1. **Farbe ist ein Ausnahmezustand, kein Dekor.** Was in Ordnung ist, bleibt farblos.
   Ein gesunder Roboter sieht fast einfarbig aus, und die eine kaputte Sache ist das
   einzig Farbige auf dem Schirm.
2. **Der Zustand wird pro Fläche genau einmal kodiert.** Nicht Randstreifen *und*
   Chip *und* farbige Zahl. Redundante Kodierung war die Hauptquelle der Unruhe.
3. **Symbol statt Wort, wo sich etwas wiederholt.** Der Level erscheint als Symbol;
   das Wort steht im Tooltip und im `aria-label`.

## Zustandskodierung

Alle Symbole kommen aus `@patternfly/react-icons`, eingefasst in PatternFlys
`<Icon status=…>`. Damit stammen die Farben aus den PF-Statustokens und der
Dunkelmodus funktioniert ohne Zutun. Kein eigenes SVG, keine Hex-Werte im SCSS.

| Level | Konstante | Symbol | `Icon status` | Wort (Tooltip + `aria-label`) |
|---|---|---|---|---|
| Fehler | `LEVEL_ERROR` (2) | `ExclamationCircleIcon` | `danger` | „Fehler“ |
| Veraltet | `LEVEL_STALE` (3) | `ClockIcon` | `info` | „Veraltet“ |
| Warnung | `LEVEL_WARN` (1) | `ExclamationTriangleIcon` | `warning` | „Warnung“ |
| OK | `LEVEL_OK` (0) | `CheckCircleIcon` | `success` | „OK“ |
| Außer Dienst | `LEVEL_INACTIVE` (−2) | `PowerOffIcon` | — (gedämpft) | „Außer Dienst“ |
| kein eigener Status | `LEVEL_NONE` (−1) | — | — | — |

Die Uhr für *veraltet* und das Ein/Aus-Zeichen für *außer Dienst* ersetzen upstreams
`QuestionCircleIcon` und `OutlinedCircleIcon`: beide benannten den Zustand nicht,
sondern nur seine Unbestimmtheit. Fünf Zustände bekommen fünf unterscheidbare
**Formen**, nicht nur fünf Farben — der Level bleibt damit bei Rot-Grün-Schwäche und
in Graustufen lesbar.

**OK schreibt in Listen nichts hin.** In der Level-Spalte des Baums und in der
Auffälligkeitenliste bleibt die Zelle bei OK leer; die Spalte behält ihre Breite,
damit beim Filtern nichts springt. Der Haken erscheint nur dort, wo genau eine Zeile
steht: im Kartenkopf des Manipulators.

**„Nur Symbol“ betrifft die Badge-Darstellung, nicht den Text der Seite.** Jedes
Symbol trägt Tooltip und `aria-label` mit dem ausgeschriebenen Wort — ohne das wäre
die Seite für Screenreader stumm, und das wäre Informationsverlust. Ausgeschrieben
bleiben außerdem: die Beschriftungen der Kennzahlen, der Zustandssatz im Kopfband
und im Detail-Panel die Zeile mit angezeigtem Level, gemeldetem Level und Grund.

## Seitenaufbau

Drei Ebenen statt einer Kette von acht Karten:

```
┌─ Kopfband (volle Breite, klebt beim Scrollen) ─────────────────────┐
│ ▲ a200_0553 — 2 Warnungen              0    2    1   34   [⏸] [⋯] │
│ /a200_0553 · Bridge verbunden · 1,0 Hz · Stand 14:32:07            │
│ ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁  Zeitachse, 30 Schnappschüsse       │
├──────────────────────────────┬─────────────────────────────────────┤
│ Manipulator                  │ Alle Diagnosen                      │
│  ┌ Arm ────┐ ┌ Greifer ───┐  │  [Suche…]        [Alle|≥Warn|≥Fehler]│
│  └─────────┘ └────────────┘  │  ⌷ Level │ Name │ Meldung           │
│ Auffälligkeiten              │  … Baum …                           │
└──────────────────────────────┴─────────────────────────────────────┘
        ↑ Klick auf einen Status → Detail-Panel schiebt sich von rechts
```

Unterhalb von 1200 px stapeln sich die Spalten: erst Manipulator und
Auffälligkeiten, dann der Baum. Das Detail-Panel wird dort Vollbild.

### Kopfband

Links Gesamtsymbol, Robotername und Zustandssatz; darunter eine gedämpfte Zeile mit
Namespace, Bridge-Zustand, Aggregat-Rate und dem Zeitstempel des **angezeigten**
Schnappschusses (nicht der Systemzeit — bei eingefrorener Zeitachse ist das der
Unterschied).

Rechts vier Kennzahlen in gleicher, ruhiger Type: **Fehler · Warnungen · Veraltet ·
Stati**. Eingefärbt und kräftiger wird nur der Wert, der nicht null ist. Daneben
Pause/Weiter und das ⋯-Menü.

Der Zustandssatz ergibt sich aus dem schlechtesten angezeigten Level aller
Blattknoten:

| schlechtester Level | Satz |
|---|---|
| Fehler | „N Fehler“ |
| Warnung | „N Warnungen“ |
| Veraltet | „N veraltete Meldungen“ |
| sonst | „betriebsbereit“ |

**Zählregeln.** Gezählt werden ausschließlich **Blattknoten** (`children.length === 0`),
sonst zählt derselbe Fehler einmal als Blatt und noch einmal in jeder Gruppe darüber.
Gezählt wird der **angezeigte** Level (`severity_level`), nicht der gemeldete — eine
herabgestufte Meldung darf die Kennzahl nicht hochtreiben.

- Fehler = `severity_level === LEVEL_ERROR`
- Warnungen = `severity_level === LEVEL_WARN`
- Veraltet = `severity_level === LEVEL_STALE`
- Stati = Anzahl aller Blattknoten

Das ist eine bewusste Verhaltensänderung: heute zählt die Errors-Tabelle mit
`level >= 2` und schluckt damit `STALE` (=3) in die Fehler. Veraltet bekommt eine
eigene Kennzahl und wird nicht mehr als Fehler ausgewiesen.

Klick auf **Fehler** setzt den Baumfilter auf „≥ Fehler“, Klick auf **Warnungen** auf
„≥ Warnung“. Steht die Kennzahl auf null, ist sie nicht klickbar — sonst führte ein
Klick auf „0 Fehler“ zu einer Filterstufe, die trotzdem veraltete Meldungen zeigt.
*Veraltet* und *Stati* sind grundsätzlich reine Anzeigen: für sie gibt es keine
passende Stufe, und ein Filter, der nur einen Level zeigt, verbirgt die Fehler
darüber.

### Zeitachse

Ersetzt `HistorySelection` samt `ProgressStepper`. 30 gleich breite, gleich **hohe**
Segmente — ein Band, kein Balkendiagramm. Farbe je Schnappschuss aus dessen `level`;
OK und außer Dienst bleiben neutralgrau, nur auffällige Schnappschüsse werden farbig.

Noch nicht gefüllte Plätze stehen als sehr blasse Segmente **links**, damit der neueste
Schnappschuss immer rechts endet und die Bandbreite konstant bleibt (Verhalten wie
heute, nur ohne die sichtbaren Leer-Steps).

Klick friert ein (setzt Pause) und wählt den Schnappschuss; der gewählte bekommt eine
Umrandung. Hover zeigt Uhrzeit und Zustandssatz dieses Schnappschusses. Darunter eine
gedämpfte Zeile: ältester Zeitpunkt links, „30 Schnappschüsse · Klick friert ein“
mittig, „jetzt“ rechts. Die drei separaten Timestamp-Zeilen von heute entfallen —
ihre Information steckt in Hover und Kopfband-Zeitstempel.

### Arbeitsfläche links: Manipulator

Inhaltlich unverändert gegenüber heute; sämtliche Felder bleiben. Neu ist die Optik:

- Karte mit **Randstreifen links** als einzigem Zustandsträger. Bei OK ist der
  Streifen grau, nicht grün.
- Im Kartenkopf rechts das Symbol plus Wort, in gedämpfter Type — hier steht der
  Zustand genau einmal, deshalb darf er ausgeschrieben werden.
- Werteliste ohne Unterstriche, Bezeichner gedämpft, Zahlen mit Tabellenziffern
  (`font-variant-numeric: tabular-nums`).
- Gelenktabelle ohne Raster, Position in Grad führend, Radiant gedämpft dahinter.
- Greifer-Fortschrittsbalken **grau statt blau**: er misst eine Öffnung, er meldet
  keinen Zustand. Die grüne Variante bei erkanntem Griff entfällt ebenfalls —
  „Objekt gehalten“ steht als Wert darunter.
- Die heutigen `StatusAlerts` werden ein ruhiger getönter Kasten mit der Meldung des
  Publishers und einem „Details“-Link, der das Detail-Panel öffnet.
- Das Dimmen außer Dienst gestellter Teilsysteme (`.manipulator-out-of-service`)
  bleibt unverändert — es verhindert, dass ein Gelenkwinkel vom stromlosen Arm als
  aktuell gelesen wird.

Die Karte rendert weiterhin nichts, wenn der Roboter keine Manipulator-Diagnose
publiziert.

### Arbeitsfläche links: Auffälligkeiten

Ersetzt die beiden `DiagnosticsTable`-Instanzen (Errors und Warnings) durch **eine**
Liste. Enthalten sind alle Blattknoten mit `severity_level >= LEVEL_WARN`, sortiert
nach Dringlichkeit **Fehler, Veraltet, Warnung**, bei gleicher Stufe nach Pfad.
Das ist bewusst *nicht* die numerische Reihenfolge der Konstanten (`LEVEL_STALE` = 3
liegt über `LEVEL_ERROR` = 2): eine veraltete Meldung darf nicht über einem echten
Fehler stehen. Die Rangfolge wird als eigene Tabelle in `utils/summary.ts` abgelegt,
damit sie nicht als versteckter Sortiervergleich in der Komponente landet.
Jede Zeile: Symbol, Name, Pfad darunter gedämpft, Meldung. Klick öffnet das
Detail-Panel.

Bei null Einträgen schrumpft der Block auf eine einzelne gedämpfte Zeile
(„keine Auffälligkeiten“) statt zweier leerer Tabellen mit je einem großen
Empty-State.

Damit entfällt auch eine irreführende Anzeige von heute: solange die Bridge nicht
verbunden ist, meldeten beide Tabellen „No Errors“ und „No Warnings“ — obwohl
schlicht keine Daten da waren.

### Arbeitsfläche rechts: Baum

`DiagnosticsTreeTable` bleibt in der Struktur, bekommt aber:

- **Level-Spalte** als erste Spalte, Breite fix (~26 px), Inhalt nur bei nicht-OK.
  Damit sind es drei Spalten: Level, Name (mit Pfad darunter), Meldung.
- **Suchfeld**: Teilstring, Groß-/Kleinschreibung egal, über Name, Pfad und Meldung.
- **Filter** als Segmentschalter: *Alle · ≥ Warnung · ≥ Fehler*. Numerisch
  `severity_level >= LEVEL_WARN` bzw. `>= LEVEL_ERROR`; da `LEVEL_STALE` (3) über
  `LEVEL_ERROR` (2) liegt, sind veraltete Meldungen in beiden Stufen enthalten. Die
  Beschriftungen sagen „≥“, damit das nicht geraten werden muss.
- Suche und Filter wirken **und**-verknüpft.
- **Sichtbarkeitsregel im Baum**: ein Knoten wird gezeigt, wenn er selbst passt oder
  ein Nachfahre passt. Vorfahren passender Knoten bleiben sichtbar und werden
  automatisch aufgeklappt, damit der Pfad lesbar bleibt.
- Ist das Ergebnis leer, steht ein Hinweis mit einem Schalter „Filter zurücksetzen“.
- Die Reihenfolge des Baums bleibt die des Aggregators. Nach Schwere sortiert wird
  nur die Auffälligkeitenliste; im Baum würde das die Pfadstruktur zerlegen.

Der eingebettete `Drawer` **verlässt** diese Komponente (siehe unten).

### Detail-Panel

Wandert von innerhalb der Baum-Karte auf **Seitenebene**. Grund: alle drei Stellen,
die einen Status auswählen können — Auffälligkeitenliste, Manipulator-Meldung,
Baumzeile — rufen schon heute dieselbe Auswahlfunktion auf, aber der Drawer steckte
im Baum und war auf 35 % von dessen Breite begrenzt. In einer rechten Spalte wäre das
ein Briefschlitz.

Ein `Drawer` umschließt künftig die gesamte Arbeitsfläche; `isExpanded` hängt an
`selectedRawName`. Inhalt:

- Symbol und Level ausgeschrieben, daneben bei Herabstufung „gemeldet: <Level>“ und
  der Grund im Klartext (wie heute, `override_reason`).
- Name, Pfad, `hardware_id`.
- Meldung in einem getönten Kasten.
- Werte als `DescriptionList` mit Tabellenziffern — ersetzt die heutige
  `<p><strong>`-Auszeichnung und die Werte-Tabelle mit Inline-`style`.

Schließen mit ✕ und mit Esc. Unter 1200 px als Vollbild-Overlay.

### ⋯-Menü und Capture

Das ⋯-Menü im Kopfband enthält:

- **„Diagnose-Paket erzeugen“** — nur mit Admin-Rechten aktiv; ohne Admin ist der
  Punkt deaktiviert und trägt den heutigen Hinweistext als Beschreibung.

`DiagnosticsCapture` verliert damit seine eigene Karte weit oben. Die Shell-Befehle,
die Redaktion der netplan-Passwörter, der Fortschritt und der Download-Link bleiben
unverändert; Fortschritt und Ergebnis erscheinen als `Alert` direkt unter dem
Kopfband.

## Randfälle

| Fall | Verhalten |
|---|---|
| Namespace ungültig | Danger-`Alert` direkt unter dem Kopfband; Arbeitsfläche wird nicht gerendert (wie heute). Der Alert-Titel bleibt wortgleich, weil `test/check-application` darauf prüft. |
| Namespace manuell nötig | `ManualNamespace` unter dem Kopfband, oberhalb der Arbeitsfläche. |
| Bridge nicht verbunden | Kopfband zeigt „Bridge getrennt“ in der Betriebszeile und ein neutrales Gesamtsymbol; die Arbeitsfläche zeigt **einen** Empty-State statt Manipulator, Auffälligkeiten und Baum. |
| Verbunden, aber noch keine Nachricht | Derselbe Empty-State mit Spinner und dem heutigen Text „Warte auf Diagnosemeldungen…“. |
| Keine Manipulator-Diagnose | Der Manipulator-Block entfällt ersatzlos; die linke Spalte enthält dann nur die Auffälligkeiten. |
| Pausiert | Pause-Schalter zeigt „Weiter“; Kopfband-Zeitstempel ist der des gewählten Schnappschusses; die Zeitachse markiert ihn. „Weiter“ leert die Historie (Verhalten wie heute). |
| Historie leer | Zeitachse als vollständig blasses Band ohne Klickverhalten. |
| Schmales Fenster (<1200 px) | Spalten stapeln, Detail-Panel wird Vollbild. |

## Dateien

**Neu**

| Datei | Zweck |
|---|---|
| `src/components/StatusBand.tsx` | Kopfband: Zustandssatz, Betriebszeile, Kennzahlen, Pause, ⋯-Menü |
| `src/components/Timeline.tsx` | Zeitachse (ersetzt `HistorySelection.tsx`) |
| `src/components/IssueList.tsx` | Auffälligkeitenliste (ersetzt `DiagnosticsTable.tsx`) |
| `src/components/DetailPanel.tsx` | Detail-Panel, aus `DiagnosticsTreeTable` herausgelöst |
| `src/components/SeverityIcon.tsx` | einzige Quelle für Symbol, Status, Wort je Level |
| `src/utils/summary.ts` | Blattknoten sammeln, Kennzahlen, Zustandssatz |
| `src/utils/treeFilter.ts` | Suche, Filter, automatisches Aufklappen |

**Geändert**

| Datei | Änderung |
|---|---|
| `src/app.tsx` | neues Layout, hält Suchtext und Filterstufe zusätzlich zum bisherigen Zustand |
| `src/app.scss` | Karten mit Randstreifen, Tabellenziffern, Zeitachse, Spalten-Umbruch |
| `src/components/DiagnosticsTreeTable.tsx` | Drawer raus, Level-Spalte rein, Suche/Filter als Props |
| `src/components/ManipulatorPanel.tsx` | Optik nach neuem Kartenstil, nutzt `SeverityIcon` |
| `src/components/DiagnosticsCapture.tsx` | Auslöser wandert ins Menü; Komponente rendert nur noch Fortschritt und Ergebnis |
| `src/components/RosConnectionManager.tsx` | baut keine Icons mehr in den Datenbaum (siehe unten) |
| `src/interfaces.ts` | `icon: JSX.Element \| null` entfällt aus `DiagnosticsEntry` |
| `test/unit/contract.test.ts` | `SOURCES` um neue Dateien ergänzen, falls Manipulator-Logik wandert |
| `test/check-application` | Zusicherung auf den Seitentitel anpassen |
| `po/de.po` | neue Zeichenketten, entfallene entfernen |

**Entfernt**: `src/components/HistorySelection.tsx`, `src/components/DiagnosticsTable.tsx`

### Aufräumen: JSX im Datenmodell

`DiagnosticsEntry.icon` hält heute ein fertiges React-Element, das
`RosConnectionManager` beim Aufbau des Baums erzeugt. Das vermischt Datenschicht und
Darstellung, verdoppelt die Level→Symbol-Zuordnung (dieselbe Abbildung steht noch
einmal in `ManipulatorPanel`) und macht den Baum in Tests unnötig schwer
vergleichbar. Mit dem Redesign wird das Feld entfernt und überall aus
`severity_level` über `SeverityIcon` gerendert.

Das ist der einzige Umbau außerhalb der Darstellung — er steht hier drin, weil die
neue Symbolzuordnung sonst als dritte Kopie derselben Tabelle entstünde.

## Was nicht dazukommt

Bewusst draußen, um den Umbau schmal zu halten:

- Keine Gruppierung nach Subsystem (Plattform/Sensoren/…): die Seite kennt nur, was
  der Aggregator liefert, und müsste die Zugehörigkeit aus Pfaden raten.
- Keine Verlaufsdiagramme einzelner Werte.
- Keine dauerhafte Speicherung von Filter oder Suche über Seitenwechsel hinweg.
- Keine Änderungen an `roslib/`, `useNamespace`, `useWebSocketUrl`, `useDiagHistory`,
  `utils/severity.ts`, `utils/manipulatorUtils.ts`, `utils/namespaceUtils.ts`.

## Tests

- Die bestehenden Unit-Tests (`severity.test.ts`, `contract.test.ts`) müssen weiter
  grün sein. `contract.test.ts` schürft Schlüsselliterale aus einer festen Dateiliste
  (`SOURCES`); wandert Manipulator-Logik in neue Dateien, muss die Liste mitwachsen,
  sonst prüft der Test stillschweigend weniger.
- Neu, im selben Runner (`node test/unit/run.js`, keine neuen Abhängigkeiten):
  - `summary.test.ts` — Kennzahlen gegen `agg-armed.json`: nur Blätter gezählt,
    angezeigter statt gemeldeter Level, `STALE` nicht als Fehler, Zustandssatz je
    schlechtestem Level.
  - `treeFilter.test.ts` — Suche findet über Name, Pfad und Meldung; Vorfahren
    passender Knoten bleiben sichtbar; leeres Ergebnis; Filterstufen einschließlich
    `STALE` in beiden Stufen.
- `test/check-application` prüft den Seitentitel und den Alert bei fehlender
  `robot.yaml`. Der Alert-Text bleibt wortgleich. Die Titel-Zusicherung wartet heute
  auf ein `h1` mit „ROS 2 Diagnostics“; künftig trägt das Kopfband als `h1` den
  Robotername samt Zustandssatz, und die Zusicherung wird darauf umgestellt. Der
  Seitenname „ROS 2 diagnostics“ bleibt erhalten — er steht in `src/manifest.json`
  und damit in Cockpits Navigation, nicht im Seiteninhalt.
- Sichtprüfung von Hand: Hell- und Dunkelmodus, Fensterbreite unter 1200 px,
  Zustände OK / Warnung / Fehler / veraltet / außer Dienst, Arm stromlos.

## Bauen und Ausliefern

Unverändert (`README.md`): gebaut wird auf der Workstation, nicht auf dem Roboter —
npm und ~500 Pakete gehören nicht in dessen apt-Historie.

```
make                                   # erzeugt dist/
rsync -a dist/ robot@<robot>:~/cockpit-ros2-diagnostics/dist/
```

Der Installer legt den Fork nach `/usr/local/share/cockpit/ros2-diagnostics` und
überdeckt damit das apt-Paket; das Verzeichnis muss `ros2-diagnostics` heißen, sonst
entsteht ein zweiter Menüpunkt statt einer Überdeckung. `dist/` ist **nicht** in git
versioniert.

## Offene Punkte

Keine. Farbwerte, Symbolnamen, Zählregeln und Filterstufen sind oben festgelegt;
die exakten PatternFly-Tokennamen werden beim Umsetzen aus `@patternfly/react-tokens`
gezogen statt hier geraten.
