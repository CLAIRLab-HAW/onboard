# Changelog — cockpit-ros2-diagnostics

Was sich wann geändert hat. Der aktuelle Stand steht in der [README](README.md).

Rückwirkend aus der Commit-Historie angelegt.

## 2026-08-19

- **Dem Greifer auf die URCap-Brücke gefolgt statt auf das stillgelegte
  `rg6_control`.** Der Zustand kommt als flaches JSON auf `rg6/bridge_state`
  von `rg6_grip_bridge`; `rg6_msgs/GripperState` hat keinen Publisher mehr.
- Historische Bezüge aus vier Quellkommentaren entfernt (`app.tsx`,
  `DiagnosticsTreeTable.tsx`, `RosConnectionManager.tsx`, `Timeline.tsx`). Die
  Begründungen bleiben, im Konjunktiv statt in der Vergangenheit — aus „it used
  to be OR-ed into `isExpanded`" wird „deliberately not OR-ed into
  `isExpanded`: that makes those rows impossible to collapse".

## 2026-08-12 (Lesbarkeit der Tabelle)

- Die Baumspalten wandern beim Lesen nicht mehr; der Chevron sitzt mittig in
  seiner Zeile und hält gegen PatternFlys Prozent-Zug.
- Aufgeklappte Zeilen gehen nach einem Filter wieder an den Leser zurück,
  statt sich von selbst erneut zu öffnen.
- Das Detail-Panel nimmt seinen Platz aus dem Inhalt und lässt den Workspace
  aus dem Splitter heraus; Zellinhalte sind in ihren Zeilen zentriert.
- Der Kartenzustand hängt allein am Streifen, die Kartenlabels haben Platz,
  die Überschrift ist ein einfacher Titel, und Symbol und Zähler sprechen für
  sich.

## 2026-07-27 bis 2026-07-31 (Grundlage)

- Manipulator-Status im Panel; deutsche Sprachunterstützung; korrigierte
  Fehler-Mappings.
- `SeverityIcon`-Komponente samt Komponententests; das `icon`-Feld ist aus
  `DiagnosticsEntry` entfallen.
