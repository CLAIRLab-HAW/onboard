# Redesign des Cockpit-Diagnosepanels — Implementierungsplan

> **Für ausführende Agenten:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development` (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe umzusetzen. Die Schritte nutzen Checkbox-Syntax (`- [ ]`) zur Nachverfolgung.

**Ziel:** Das Cockpit-Diagnosepanel bekommt ein ruhigeres, dichteres Layout mit Kopfband, Zeitachse, zweispaltiger Arbeitsfläche und Detail-Panel auf Seitenebene — ohne dass eine einzige heute angezeigte Information verschwindet.

**Architektur:** Die Datenschicht (`roslib/`, `RosConnectionManager`, `hooks/`, `utils/severity.ts`, `utils/manipulatorUtils.ts`) bleibt unangetastet bis auf eine Ausnahme: das fertige React-Element in `DiagnosticsEntry.icon` fällt weg, damit die Level→Symbol-Zuordnung nur noch an einer Stelle steht. Darüber entstehen zwei reine Logikmodule (`utils/summary.ts`, `utils/treeFilter.ts`), die mit echten Unit-Tests abgesichert sind, und darauf sechs Darstellungskomponenten. `app.tsx` wird vom Karten-Stapel zum Layout-Rahmen.

**Tech-Stack:** TypeScript (strict, `exactOptionalPropertyTypes`), React 18, PatternFly v6 (`react-core`, `react-icons`, `react-table`), SCSS, esbuild. Tests: der vorhandene Mini-Runner `test/unit/run.js` (esbuild + node, kein Framework), Komponenten über `react-dom/server`.

## Global Constraints

Diese Vorgaben gelten für **jede** Aufgabe:

- **Keine neuen npm-Abhängigkeiten.** `react-dom/server` ist bereits vorhanden (`react-dom` ist Laufzeitabhängigkeit) und deckt Komponententests ab.
- **Nicht committen und nicht pushen.** Der Benutzer committet selbst. Jede Aufgabe endet mit einem Prüfschritt, nicht mit `git commit`.
- **Gearbeitet wird auf `main`**, ohne Worktree.
- **Alle sichtbaren Zeichenketten** laufen durch `cockpit.gettext` (`const _ = cockpit.gettext;`) als **englische** Literale; die deutschen Fassungen stehen in `po/de.po`.
- **Keine Farbwerte in SCSS oder JSX.** Zustandsfarben ausschließlich über PatternFlys `<Icon status="danger|warning|info|success">` und PF-Tokens (`var(--pf-t--global--…)`).
- **ESLint:** Einrückung 4 Leerzeichen, `semi: always`, `react/jsx-indent: 4`. Anführungszeichen sind frei (`quotes: off`).
- **TypeScript:** `strict` und `exactOptionalPropertyTypes` sind an — ein optionales Prop darf nicht explizit `undefined` bekommen; den Schlüssel stattdessen weglassen (`{...(cond ? { className: "x" } : {})}`, wie im Bestand).
- **Prüfbefehle** (aus `robot/cockpit-ros2-diagnostics/`):
  - `make check-unit` — Unit-Tests (`node test/unit/run.js`). **Muss grün sein.** Das ist das eigentliche Tor.
  - `npm run eslint` — ESLint über `src/`. **Muss ohne Meldung durchlaufen.**
  - `npm run stylelint` — Stylelint über `src/*.{css,scss}`; nur bei SCSS-Änderungen nötig.
  - `npx tsc --noEmit` — Typprüfung. **Läuft in diesem Repo nicht fehlerfrei** und hat nie fehlerfrei gelaufen: es gibt vorbestehende Fehler in `src/roslib/`, `src/components/RosConnectionManager.tsx`, `src/components/DiagnosticsCapture.tsx` sowie in PatternFly- und `isomorphic-ws`-Typdefinitionen — allesamt untypisierte ROS-Nutzlasten und Abhängigkeitslücken, nichts aus diesem Umbau. Maßstab ist deshalb **keine neuen Fehler**, nicht „null Fehler“: Ausgabe gegen `.superpowers/sdd/2026-07-31-diagnostics-redesign/tsc-baseline.txt` vergleichen, etwa mit
    `diff <(npx tsc --noEmit 2>&1 | sort) .superpowers/sdd/2026-07-31-diagnostics-redesign/tsc-baseline.txt`.
    Zeilennummern verschieben sich beim Bearbeiten einer Datei; entscheidend ist, dass keine **neue** Fehlermeldung und keine Meldung in einer neu angelegten Datei auftaucht.
  - `make` — Bau nach `dist/`
  - **Nicht** `make codecheck` verwenden: das Ziel ruft `test/common/static-code` auf, und dessen ESLint-Schritt wird still übersprungen, weil `eslint` nicht auf dem PATH liegt. Der Aufruf meldet Erfolg, ohne geprüft zu haben.
- **`dist/` ist nicht in git versioniert** und wird per `rsync` auf den Roboter gebracht. Kein Bauen auf dem Roboter.
- Die Spec liegt unter `docs/superpowers/specs/2026-07-31-diagnostics-redesign-design.md` und ist bei Zweifelsfragen maßgeblich.

---

## Dateistruktur

**Neu**

| Datei | Verantwortung |
|---|---|
| `src/components/SeverityIcon.tsx` | Einzige Quelle für Level → Symbol, PF-Status und Wort. Exportiert `SeverityIcon` und `severityLabel`. |
| `src/utils/summary.ts` | Blattknoten, Kennzahlen, Zustandssatz, Dringlichkeitsrangfolge, Aktualisierungsrate. Reine Funktionen, keine JSX. |
| `src/utils/treeFilter.ts` | Suche und Filterstufe über den Baum; liefert Sichtbarkeits- und Aufklappmengen. Reine Funktionen. |
| `src/components/StatusBand.tsx` | Kopfband: Zustandssatz, Betriebszeile, Kennzahlen, Pause, ⋯-Menü. |
| `src/components/Timeline.tsx` | Zeitachse über die Schnappschuss-Historie. Ersetzt `HistorySelection.tsx`. |
| `src/components/IssueList.tsx` | Auffälligkeitenliste. Ersetzt beide `DiagnosticsTable`-Instanzen. |
| `src/components/DetailPanel.tsx` | Inhalt des Detail-Panels, aus `DiagnosticsTreeTable` herausgelöst. |
| `test/unit/summary.test.ts` | Kennzahlen, Zustandssatz, Sortierung, Rate. |
| `test/unit/treefilter.test.ts` | Suche, Filterstufen, Sichtbarkeit von Vorfahren. |
| `test/unit/components.test.ts` | Auszeichnungs-Rauchtest über `renderToStaticMarkup`. |

**Geändert:** `src/app.tsx`, `src/app.scss`, `src/interfaces.ts`, `src/components/RosConnectionManager.tsx`, `src/components/DiagnosticsTreeTable.tsx`, `src/components/ManipulatorPanel.tsx`, `src/components/DiagnosticsCapture.tsx`, `test/unit/cockpit-stub.ts`, `test/unit/contract.test.ts`, `test/check-application`, `po/de.po`

**Entfernt:** `src/components/HistorySelection.tsx`, `src/components/DiagnosticsTable.tsx`

---

## Task 1: Zentrale Level-Darstellung

**Files:**
- Create: `src/components/SeverityIcon.tsx`
- Modify: `po/de.po`
- Test: `test/unit/components.test.ts`

**Interfaces:**
- Consumes: `LEVEL_*` aus `src/utils/severity.ts` (unverändert).
- Produces:
  - `severityLabel(level: number): string` — englisches Literal, durch `cockpit.gettext` gereicht.
  - `<SeverityIcon level={number} hideOk?={boolean} />` — rendert `null` für `LEVEL_NONE` und (bei `hideOk`) für `LEVEL_OK`.

Warum `title` statt PatternFly-`Tooltip`: das Symbol steht in bis zu 34 Tabellenzeilen gleichzeitig. Ein natives `title` kostet nichts, überlebt `renderToStaticMarkup` und vermeidet 34 Popper-Instanzen im DOM. Das `aria-label` trägt dieselbe Zeichenkette, damit Screenreader den Zustand vorlesen.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

`test/unit/components.test.ts`:

```ts
/*
 * Markup smoke tests.
 *
 * `react-dom/server` is already a dependency of the app, so components can be
 * rendered to static markup in node without jsdom and without a test framework.
 * These tests do not check layout -- they check the contract the rest of the
 * page relies on: that a level renders one recognisable symbol, that OK writes
 * nothing into a list, and that every symbol carries its word for screen
 * readers.
 */
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

import { SeverityIcon, severityLabel } from "../../src/components/SeverityIcon";
import {
    LEVEL_ERROR, LEVEL_INACTIVE, LEVEL_NONE, LEVEL_OK, LEVEL_STALE, LEVEL_WARN,
} from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

/* ------------------------------------------------------------------ labels */

check(severityLabel(LEVEL_ERROR) === "Error", "LEVEL_ERROR must be labelled Error");
check(severityLabel(LEVEL_STALE) === "Stale", "LEVEL_STALE must be labelled Stale");
check(severityLabel(LEVEL_WARN) === "Warning", "LEVEL_WARN must be labelled Warning");
check(severityLabel(LEVEL_OK) === "OK", "LEVEL_OK must be labelled OK");
check(severityLabel(LEVEL_INACTIVE) === "Out of service", "LEVEL_INACTIVE must be labelled Out of service");

/* ------------------------------------------------------------------ markup */

const markup = (level: number, hideOk = false) =>
    renderToStaticMarkup(React.createElement(SeverityIcon, { level, hideOk }));

for (const level of [LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN, LEVEL_INACTIVE]) {
    const html = markup(level);
    check(html.includes(`aria-label="${severityLabel(level)}"`),
          `level ${level} must expose its word as aria-label`);
    check(html.includes("<svg"), `level ${level} must render a symbol`);
}

// Five states must be told apart by *shape*, not only by colour, otherwise the
// page is unreadable in greyscale and with red-green colour blindness.
//
// Compared is the SVG path data only. Comparing whole markup would pass
// trivially -- the label, the title and the status class already differ per
// level, so the assertion would prove nothing about the drawing.
const pathData = (level: number) =>
    (markup(level).match(/ d="[^"]*"/g) ?? []).join("|");
const shapes = [LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN, LEVEL_INACTIVE, LEVEL_OK].map(pathData);
check(shapes.every(shape => shape !== ""), "every level must render actual path data");
check(new Set(shapes).size === shapes.length, "every level needs a distinct symbol shape");

/* -------------------------------------------------- OK writes nothing in lists */

check(markup(LEVEL_OK, true) === "", "with hideOk, LEVEL_OK must render nothing");
check(markup(LEVEL_OK).includes("<svg"), "without hideOk, LEVEL_OK still renders its tick");
check(markup(LEVEL_NONE) === "", "LEVEL_NONE has no status of its own and must render nothing");

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} component assertion(s) failed`);
}

console.log("components: OK (5 labels, 5 distinct shapes, OK-is-silent rule)");
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: FAIL — `Could not resolve "../../src/components/SeverityIcon"`

- [ ] **Schritt 3: Die Komponente schreiben**

`src/components/SeverityIcon.tsx`:

```tsx
/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg.
 *
 * Cockpit ROS 2 Diagnostics is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version.
 *
 * Cockpit ROS 2 Diagnostics is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with Cockpit; If not, see <http://www.gnu.org/licenses/>.
 */

import React from 'react';
import { Icon } from "@patternfly/react-core";
import {
    CheckCircleIcon,
    ClockIcon,
    ExclamationCircleIcon,
    ExclamationTriangleIcon,
    PowerOffIcon,
} from "@patternfly/react-icons";

import cockpit from 'cockpit';

import {
    LEVEL_ERROR,
    LEVEL_INACTIVE,
    LEVEL_OK,
    LEVEL_STALE,
    LEVEL_WARN,
} from "../utils/severity";

const _ = cockpit.gettext;

/*
 * One place that decides how a severity looks.
 *
 * Five states get five distinguishable *shapes*, not just five colours, so the
 * page stays readable in greyscale and with red-green colour blindness. The
 * clock and the power symbol replace upstream's question mark and empty circle:
 * those named the uncertainty, not the state -- a stale status means "no fresh
 * message", and an inactive one means "deliberately switched off".
 *
 * Colours come from PatternFly's `<Icon status>`, never from our own SCSS, so
 * Cockpit's dark mode needs no extra work.
 */
export const severityLabel = (level: number): string => {
    switch (level) {
    case LEVEL_ERROR:
        return _("Error");
    case LEVEL_STALE:
        return _("Stale");
    case LEVEL_WARN:
        return _("Warning");
    case LEVEL_OK:
        return _("OK");
    case LEVEL_INACTIVE:
        return _("Out of service");
    default:
        return _("No data");
    }
};

const glyphFor = (level: number): React.ReactElement | null => {
    switch (level) {
    case LEVEL_ERROR:
        return <Icon status="danger"><ExclamationCircleIcon /></Icon>;
    case LEVEL_STALE:
        return <Icon status="info"><ClockIcon /></Icon>;
    case LEVEL_WARN:
        return <Icon status="warning"><ExclamationTriangleIcon /></Icon>;
    case LEVEL_OK:
        return <Icon status="success"><CheckCircleIcon /></Icon>;
    case LEVEL_INACTIVE:
        return <Icon className="severity-icon-inactive"><PowerOffIcon /></Icon>;
    default:
        return null;
    }
};

/*
 * `hideOk` is what keeps repeating lists calm: in the tree and in the issue
 * list a healthy status writes nothing at all, because "everything is fine" is
 * not something anybody scans for. The tick is only drawn where exactly one
 * line stands, such as a manipulator card header.
 *
 * A native `title` rather than a PatternFly Tooltip: this renders in up to 34
 * table rows at once, and the word has to reach screen readers through
 * `aria-label` in any case.
 */
export const SeverityIcon = ({
    level,
    hideOk = false,
}: {
    level: number,
    hideOk?: boolean,
}) => {
    if (hideOk && level === LEVEL_OK) {
        return null;
    }

    const glyph = glyphFor(level);
    if (!glyph) {
        return null;
    }

    const label = severityLabel(level);
    return (
        <span className="severity-icon" role="img" aria-label={label} title={label}>
            {glyph}
        </span>
    );
};
```

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: PASS — `components: OK (5 labels, 5 distinct shapes, OK-is-silent rule)`

- [ ] **Schritt 5: Übersetzungen ergänzen**

`po/de.po` muss Einträge für alle fünf Wörter plus `No data` haben. Vorhandene `msgid`s nicht doppeln — `Warning`, `Error`, `Stale`, `Out of service`, `OK` und `No data` stammen aus `ManipulatorPanel.tsx` und sind wahrscheinlich schon da. Prüfen mit:

```bash
for s in "Error" "Stale" "Warning" "OK" "Out of service" "No data"; do
  grep -q "msgid \"$s\"" po/de.po && echo "vorhanden: $s" || echo "FEHLT: $s"
done
```

Fehlende nachtragen, Muster wie im Bestand:

```
msgid "Stale"
msgstr "Veraltet"
```

Gewünschte Übersetzungen: `Error`→`Fehler`, `Stale`→`Veraltet`, `Warning`→`Warnung`, `OK`→`OK`, `Out of service`→`Außer Dienst`, `No data`→`Keine Daten`.

- [ ] **Schritt 6: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck
```
Erwartet: alle drei ohne Fehler. Danach dem Benutzer den Stand melden — **nicht committen**.

---

## Task 2: JSX aus dem Datenmodell entfernen

**Files:**
- Modify: `src/interfaces.ts:36` (Feld `icon`), `src/components/RosConnectionManager.tsx:65-84,117,152`, `src/components/DiagnosticsTreeTable.tsx:129,224`, `src/components/DiagnosticsTable.tsx:83`
- Test: bestehende Suite plus Typprüfung

**Interfaces:**
- Consumes: `SeverityIcon` aus Task 1.
- Produces: `DiagnosticsEntry` ohne `icon`-Feld. Alle späteren Aufgaben gehen davon aus, dass Symbole aus `severity_level` gerendert werden.

Warum jetzt und nicht später: die Testfixturen der Tasks 3 und 4 bauen `DiagnosticsEntry`-Literale von Hand. Solange das Feld existiert, müsste jede Fixture ein `icon: null` mitschleppen, das kurz darauf wieder verschwindet.

- [ ] **Schritt 1: Feld aus dem Interface entfernen**

In `src/interfaces.ts` die letzten beiden Zeilen von `DiagnosticsEntry` ändern — `children` bleibt, `icon` fällt weg:

```ts
    children: DiagnosticsEntry[];
}
```

Die Zeile `icon: JSX.Element | null;` und den darüberstehenden Kommentar löschen.

- [ ] **Schritt 2: Typprüfung laufen lassen, alle Fundstellen einsammeln**

Ausführen: `npx tsc --noEmit`
Erwartet: FAIL mit Fehlern in `RosConnectionManager.tsx`, `DiagnosticsTreeTable.tsx` und `DiagnosticsTable.tsx`. Diese Liste ist die Arbeitsanweisung für Schritt 3 — der Compiler findet die Fundstellen zuverlässiger als eine Suche.

- [ ] **Schritt 3: Erzeugerseite ausbauen**

In `src/components/RosConnectionManager.tsx`:

- die Funktionen `iconFor` und `assignIcons` vollständig löschen (Zeilen 65–84),
- den Aufruf `assignIcons(root);` in `buildDiagnosticsTree` löschen und den Kommentar darüber auf den verbleibenden Schritt kürzen:

```tsx
    // Propagate overridden levels into the analyzer groups above them.
    rollUpOverrides(root);

    return root;
```

- die Zeile `icon: null, // Assigned once the levels are final` aus dem Objektliteral löschen,
- die dadurch unbenutzten Importe entfernen: `Icon` aus `@patternfly/react-core` sowie `CheckCircleIcon`, `ExclamationCircleIcon`, `ExclamationTriangleIcon`, `OutlinedCircleIcon`, `QuestionCircleIcon` aus `@patternfly/react-icons`. Welche davon noch anderweitig gebraucht werden, sagt ESLint in Schritt 5.

- [ ] **Schritt 4: Verbraucherseite umstellen**

In `src/components/DiagnosticsTreeTable.tsx`:

- Import ergänzen: `import { SeverityIcon } from "./SeverityIcon";`
- in `treeRow.props` die Zeile `icon: diag.icon,` **ersatzlos streichen**. Das Symbol wandert in Task 9 in eine eigene Level-Spalte; ein zusätzliches Symbol direkt vor dem Namen wäre danach die zweite Kodierung derselben Aussage.
- im Drawer-Titel `{selectedEntry.icon}` ersetzen:

```tsx
<Title headingLevel="h4" size="md">
    <SeverityIcon level={selectedEntry.severity_level} /> {selectedEntry.name}
</Title>
```

In `src/components/DiagnosticsTable.tsx` (fällt in Task 7 ganz weg, muss bis dahin aber bauen):

- Import ergänzen: `import { SeverityIcon } from "./SeverityIcon";`
- `{diag.icon}` ersetzen durch `<SeverityIcon level={diag.severity_level} hideOk />`

- [ ] **Schritt 5: Prüfen**

```bash
npx tsc --noEmit && make check-unit && make codecheck
```
Erwartet: `tsc` ohne Fehler, `check-unit` grün (`severity` und `contract` bauen den Baum und müssen unverändert durchlaufen), `codecheck` ohne unbenutzte Importe.

`ManipulatorPanel.tsx` bleibt in dieser Aufgabe unangetastet: es nutzt `entry.icon` nicht, sondern eine eigene `severityStyle`-Tabelle. Die verschwindet in Task 12.

---

## Task 3: Kennzahlen und Zustandssatz

**Files:**
- Create: `src/utils/summary.ts`
- Modify: `test/unit/cockpit-stub.ts`
- Test: `test/unit/summary.test.ts`

**Interfaces:**
- Consumes: `DiagnosticsEntry` (ohne `icon`, Task 2), `LEVEL_*`, `DiagnosticsStatus`.
- Produces:
  - `leafEntries(entries: DiagnosticsEntry[]): DiagnosticsEntry[]`
  - `summarise(entries: DiagnosticsEntry[]): DiagnosticsSummary` mit `{ errors, warnings, stale, total, worst }`
  - `headline(summary: DiagnosticsSummary): string`
  - `issueEntries(entries: DiagnosticsEntry[]): DiagnosticsEntry[]`
  - `updateRateHz(history: DiagnosticsStatus[]): number | null`

- [ ] **Schritt 1: Den Stub um `ngettext` erweitern**

`test/unit/cockpit-stub.ts` kennt bisher nur `gettext` und `format`. Der Zustandssatz braucht Pluralformen:

```ts
// Stand-in for the `cockpit` module outside the browser. Only the calls the
// tested code paths use; translation is identity, so tests assert English.
const cockpit = {
    gettext: (s: string) => s,
    ngettext: (singular: string, plural: string, n: number) => (n === 1 ? singular : plural),
    format: (fmt: string, ...args: unknown[]) =>
        fmt.replace(/\$(\d)/g, (_m, i) => String(args[Number(i)])),
};
export default cockpit;
```

- [ ] **Schritt 2: Den fehlschlagenden Test schreiben**

`test/unit/summary.test.ts`:

```ts
/*
 * Counting rules for the status band.
 *
 * Two traps this pins down:
 *
 *  1. Counting every node instead of the leaves reports the same fault once as
 *     a leaf and again in every analyzer group above it. `agg-armed.json` has
 *     24 aggregator statuses but only 15 leaves.
 *  2. `LEVEL_STALE` is numerically 3 and therefore *above* `LEVEL_ERROR` = 2.
 *     The old errors table filtered with `level >= 2` and silently swallowed
 *     stale statuses into the error count; stale now has a counter of its own,
 *     and it must not show up as an error.
 *
 * Counted is always the *displayed* level, never the reported one -- a
 * downgraded status must not drive the headline.
 */
import live from "./agg-armed.json";
import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
import { DiagnosticsEntry, DiagnosticsStatus } from "../../src/interfaces";
import {
    headline, issueEntries, leafEntries, summarise, updateRateHz,
} from "../../src/utils/summary";
import {
    LEVEL_ERROR, LEVEL_INACTIVE, LEVEL_OK, LEVEL_STALE, LEVEL_WARN,
} from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

/* ------------------------------------------------- against the real capture */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const tree = buildDiagnosticsTree(live as any[]);
const real = summarise(tree);

check(leafEntries(tree).length === 15, "agg-armed.json has 15 leaves, not 24 statuses");
check(real.total === 15, "total counts leaves");
// The capture reports five ERRORs. Two of them are leaves and both are
// downgraded (jitter -> warning, joystick -> out of service); the other three
// are the analyzer groups above them.
check(real.errors === 0, "no leaf in the capture is displayed as an error");
check(real.warnings === 1, "the downgraded jitter status is the single warning");
check(real.stale === 0, "the capture has no stale status");
check(real.worst === LEVEL_WARN, "worst displayed level is the warning");
check(headline(real) === "1 warning", "headline names the warning count");

const issues = issueEntries(tree);
check(issues.length === 1, "only the warning is an issue -- out of service is not");
check(issues[0].name.trim() === "Hardware Components Activity", "the jitter status is the issue");

/* ------------------------------------------- synthetic tree for the corners */

const leaf = (name: string, level: number): DiagnosticsEntry => ({
    name,
    path: `group/${name}`,
    rawName: `group/${name}`,
    message: `${name} message`,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values: null,
    children: [],
});

const group = (name: string, children: DiagnosticsEntry[]): DiagnosticsEntry => ({
    ...leaf(name, Math.max(...children.map(c => c.severity_level))),
    children,
});

const mixed = [group("g", [
    leaf("boom", LEVEL_ERROR),
    leaf("old", LEVEL_STALE),
    leaf("hmm", LEVEL_WARN),
    leaf("fine", LEVEL_OK),
    leaf("off", LEVEL_INACTIVE),
])];
const s = summarise(mixed);

check(s.total === 5, "the group itself is not counted");
check(s.errors === 1, "stale must not be counted as an error");
check(s.stale === 1, "stale gets its own counter");
check(s.warnings === 1, "warnings are counted exactly");
check(headline(s) === "1 error", "an error outranks warning and stale in the headline");
check(headline(summarise([group("g", [leaf("old", LEVEL_STALE)])])) === "1 stale message",
      "stale reaches the headline when nothing worse is present");
check(headline(summarise([group("g", [leaf("fine", LEVEL_OK), leaf("off", LEVEL_INACTIVE)])])) === "operational",
      "OK and out of service together read as operational");
check(headline(summarise([])) === "operational", "an empty tree does not claim a fault");

/* ------------------------------------------------- urgency, not numeric order */

// LEVEL_STALE (3) sorts above LEVEL_ERROR (2) numerically. For an operator that
// is the wrong way round: a message that stopped arriving must not outrank a
// fault that is being reported right now.
const order = issueEntries(mixed).map(e => e.severity_level);
check(JSON.stringify(order) === JSON.stringify([LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN]),
      "issues sort error, stale, warning -- not by the numeric constants");

/* -------------------------------------------------------------------- rate */

const at = (ms: number): DiagnosticsStatus => ({ timestamp: ms, level: LEVEL_OK, diagnostics: [] });
check(updateRateHz([at(0), at(1000), at(2000), at(3000)]) === 1, "four samples one second apart are 1 Hz");
check(updateRateHz([at(0)]) === null, "a single sample has no rate");
check(updateRateHz([]) === null, "an empty history has no rate");

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} summary assertion(s) failed`);
}

console.log("summary: OK (leaf counting, stale vs error, headline, urgency order, rate)");
```

- [ ] **Schritt 3: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: `node test/unit/run.js summary`
Erwartet: FAIL — `Could not resolve "../../src/utils/summary"`

- [ ] **Schritt 4: Das Modul schreiben**

`src/utils/summary.ts` (Lizenzkopf wie in Task 1, mit `Copyright (C) 2026 CLAIRLab, HAW Hamburg.`):

```ts
import cockpit from 'cockpit';

import { DiagnosticsEntry, DiagnosticsStatus } from "../interfaces";
import { LEVEL_ERROR, LEVEL_OK, LEVEL_STALE, LEVEL_WARN } from "./severity";

const _ = cockpit.gettext;

export interface DiagnosticsSummary {
    errors: number;
    warnings: number;
    stale: number;
    // Every leaf, including the ones that are OK or out of service.
    total: number;
    // Worst *displayed* level across all leaves; LEVEL_OK for an empty tree.
    worst: number;
}

/*
 * Only leaves carry a status of their own.
 *
 * The aggregator publishes one status per analyzer group as well, computed from
 * its children. Counting those too reports the same fault once as a leaf and
 * again for every group above it -- on the a200 capture that is 24 statuses for
 * 15 actual ones.
 */
export const leafEntries = (entries: DiagnosticsEntry[]): DiagnosticsEntry[] =>
    entries.flatMap(entry => (entry.children.length === 0 ? [entry] : leafEntries(entry.children)));

export const summarise = (entries: DiagnosticsEntry[]): DiagnosticsSummary => {
    const leaves = leafEntries(entries);
    const count = (level: number) => leaves.filter(leaf => leaf.severity_level === level).length;

    return {
        errors: count(LEVEL_ERROR),
        warnings: count(LEVEL_WARN),
        stale: count(LEVEL_STALE),
        total: leaves.length,
        worst: leaves.reduce((worst, leaf) => Math.max(worst, leaf.severity_level), LEVEL_OK),
    };
};

/*
 * The sentence in the status band.
 *
 * Deliberately not derived from `worst` alone: the operator wants the count of
 * the worst thing, not just its name.
 */
export const headline = (summary: DiagnosticsSummary): string => {
    if (summary.errors > 0)
        return cockpit.format(cockpit.ngettext("$0 error", "$0 errors", summary.errors), summary.errors);
    if (summary.warnings > 0)
        return cockpit.format(cockpit.ngettext("$0 warning", "$0 warnings", summary.warnings), summary.warnings);
    if (summary.stale > 0)
        return cockpit.format(
            cockpit.ngettext("$0 stale message", "$0 stale messages", summary.stale), summary.stale);
    return _("operational");
};

/*
 * How urgent a level is for whoever is standing in front of the robot.
 *
 * NOT the numeric order of the constants: LEVEL_STALE is 3 and would sort above
 * LEVEL_ERROR = 2. A message that stopped arriving must not push a fault that is
 * being reported right now further down the list. Kept as a table so the
 * reversal is visible instead of hiding in a comparator.
 */
const URGENCY: Record<number, number> = {
    [LEVEL_ERROR]: 0,
    [LEVEL_STALE]: 1,
    [LEVEL_WARN]: 2,
};

const urgencyOf = (level: number): number => URGENCY[level] ?? Number.MAX_SAFE_INTEGER;

// Leaves worth acting on, worst first, ties broken by path so the order is
// stable between snapshots.
export const issueEntries = (entries: DiagnosticsEntry[]): DiagnosticsEntry[] =>
    leafEntries(entries)
            .filter(entry => entry.severity_level >= LEVEL_WARN)
            .sort((a, b) =>
                urgencyOf(a.severity_level) - urgencyOf(b.severity_level) ||
                a.path.localeCompare(b.path));

/*
 * How fast the aggregator is publishing, measured over the whole retained
 * history rather than the last gap -- a single late message should not make the
 * band flicker.
 */
export const updateRateHz = (history: DiagnosticsStatus[]): number | null => {
    if (history.length < 2)
        return null;

    const span = history[history.length - 1].timestamp - history[0].timestamp;
    if (span <= 0)
        return null;

    return ((history.length - 1) * 1000) / span;
};
```

- [ ] **Schritt 5: Test laufen lassen, Erfolg bestätigen**

Ausführen: `node test/unit/run.js summary`
Erwartet: PASS — `summary: OK (leaf counting, stale vs error, headline, urgency order, rate)`

- [ ] **Schritt 6: Neue Zeichenketten übersetzen**

In `po/de.po` ergänzen (Pluralform beachten, `nplurals=2`):

```
msgid "$0 error"
msgid_plural "$0 errors"
msgstr[0] "$0 Fehler"
msgstr[1] "$0 Fehler"

msgid "$0 warning"
msgid_plural "$0 warnings"
msgstr[0] "$0 Warnung"
msgstr[1] "$0 Warnungen"

msgid "$0 stale message"
msgid_plural "$0 stale messages"
msgstr[0] "$0 veraltete Meldung"
msgstr[1] "$0 veraltete Meldungen"

msgid "operational"
msgstr "betriebsbereit"
```

- [ ] **Schritt 7: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck
```
Erwartet: alle grün, insbesondere `summary`, `severity`, `contract` und `components`.

---

## Task 4: Suche und Filterstufe

**Files:**
- Create: `src/utils/treeFilter.ts`
- Test: `test/unit/treefilter.test.ts`

**Interfaces:**
- Consumes: `DiagnosticsEntry`, `LEVEL_*`.
- Produces:
  - `type FilterLevel = "all" | "warn" | "error"`
  - `filterTree(entries, query: string, level: FilterLevel): TreeFilterResult` mit `{ visible: Set<string>, expand: Set<string>, matches: number }`. Die Mengen enthalten `rawName`-Werte.

Warum Mengen statt eines beschnittenen Baums: der Baum wird bereits rekursiv gerendert, und ein zweiter, kopierter Baum würde die Knotenidentität zerstören, an der Auswahl (`selectedRawName`) und Aufklappzustand hängen.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

`test/unit/treefilter.test.ts`:

```ts
/*
 * Search and level filter over the diagnostics tree.
 *
 * The rule that makes this non-trivial: a node stays visible when *it* matches
 * or when any descendant matches, because otherwise a hit three levels down
 * would appear without the path that explains where it lives.
 */
import { DiagnosticsEntry } from "../../src/interfaces";
import { filterTree } from "../../src/utils/treeFilter";
import { LEVEL_ERROR, LEVEL_OK, LEVEL_STALE, LEVEL_WARN } from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

const node = (
    name: string,
    level: number,
    message: string,
    children: DiagnosticsEntry[] = [],
): DiagnosticsEntry => ({
    name,
    path: `root/${name}`,
    rawName: `root/${name}`,
    message,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values: null,
    children,
});

const camera = node("camera_0", LEVEL_OK, "streaming 30 fps");
const imu = node("imu_0", LEVEL_WARN, "gyro bias not converged");
const gps = node("gps_0", LEVEL_STALE, "no message since 14:29:51");
const sensors = node("Sensors", LEVEL_STALE, "1 of 3 flagged", [camera, imu, gps]);
const motor = node("motor", LEVEL_ERROR, "overcurrent");
const platform = node("Platform", LEVEL_ERROR, "Error", [motor]);
const tree = [sensors, platform];

/* ------------------------------------------------------------ no filtering */

const none = filterTree(tree, "", "all");
check(none.visible.size === 6, "with no query and no filter everything is visible");
check(none.expand.size === 0, "an unfiltered tree must not be force-expanded");

/* ------------------------------------------------------------------ search */

const search = filterTree(tree, "gyro", "all");
check(search.visible.has(imu.rawName), "the matching node is visible");
check(search.visible.has(sensors.rawName), "its ancestor stays visible so the path is readable");
check(!search.visible.has(camera.rawName), "a non-matching sibling is hidden");
check(!search.visible.has(platform.rawName), "an unrelated branch is hidden");
check(search.expand.has(sensors.rawName), "ancestors of a hit are expanded");
check(!search.expand.has(imu.rawName), "the hit itself is not expanded");
check(search.matches === 1, "one node matched");

check(filterTree(tree, "GYRO", "all").visible.has(imu.rawName), "search ignores case");
check(filterTree(tree, "root/gps_0", "all").visible.has(gps.rawName), "search covers the path");
check(filterTree(tree, "camera_0", "all").visible.has(camera.rawName), "search covers the name");
check(filterTree(tree, "overcurrent", "all").visible.has(motor.rawName), "search covers the message");
check(filterTree(tree, "nothing here", "all").matches === 0, "a miss reports zero matches");
check(filterTree(tree, "nothing here", "all").visible.size === 0, "a miss hides everything");

/* ------------------------------------------------------------------ levels */

const warn = filterTree(tree, "", "warn");
check(warn.visible.has(imu.rawName), "warn keeps warnings");
check(warn.visible.has(gps.rawName), "warn keeps stale -- LEVEL_STALE is above LEVEL_WARN");
check(warn.visible.has(motor.rawName), "warn keeps errors");
check(!warn.visible.has(camera.rawName), "warn drops OK");

const error = filterTree(tree, "", "error");
check(error.visible.has(motor.rawName), "error keeps errors");
check(error.visible.has(gps.rawName), "error keeps stale -- numerically 3 is above 2");
check(!error.visible.has(imu.rawName), "error drops warnings");

/* -------------------------------------------------------------- combined */

const both = filterTree(tree, "gps", "error");
check(both.visible.has(gps.rawName), "search and filter combine with AND");
check(!both.visible.has(motor.rawName), "the error that does not match the search is dropped");

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} tree-filter assertion(s) failed`);
}

console.log("treeFilter: OK (ancestors kept, case-insensitive, stale in both levels, AND)");
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: `node test/unit/run.js treefilter`
Erwartet: FAIL — `Could not resolve "../../src/utils/treeFilter"`

- [ ] **Schritt 3: Das Modul schreiben**

`src/utils/treeFilter.ts` (Lizenzkopf wie oben):

```ts
import { DiagnosticsEntry } from "../interfaces";
import { LEVEL_ERROR, LEVEL_WARN } from "./severity";

/*
 * "warn" and "error" are thresholds, not exact levels -- hence the >= labels in
 * the UI. LEVEL_STALE is numerically 3 and therefore contained in both: a
 * status that stopped arriving is at least as interesting as the error it might
 * be hiding.
 */
export type FilterLevel = "all" | "warn" | "error";

export interface TreeFilterResult {
    // rawNames of every node that must be rendered.
    visible: Set<string>;
    // rawNames that must be expanded so a match deeper down is reachable. Only
    // ancestors -- a match itself keeps whatever expansion state the user set.
    expand: Set<string>;
    // How many nodes matched on their own; 0 drives the "nothing found" state.
    matches: number;
}

const thresholdFor = (level: FilterLevel): number | null => {
    if (level === "warn") return LEVEL_WARN;
    if (level === "error") return LEVEL_ERROR;
    return null;
};

const collect = (entries: DiagnosticsEntry[], into: Set<string>): void => {
    entries.forEach(entry => {
        into.add(entry.rawName);
        collect(entry.children, into);
    });
};

export const filterTree = (
    entries: DiagnosticsEntry[],
    query: string,
    level: FilterLevel,
): TreeFilterResult => {
    const needle = query.trim().toLowerCase();
    const threshold = thresholdFor(level);

    // Nothing to do: show the tree as the aggregator ordered it and leave the
    // user's own expansion state alone.
    if (needle === "" && threshold === null) {
        const visible = new Set<string>();
        collect(entries, visible);
        return { visible, expand: new Set<string>(), matches: visible.size };
    }

    const visible = new Set<string>();
    const expand = new Set<string>();
    let matches = 0;

    const matchesSelf = (entry: DiagnosticsEntry): boolean => {
        if (threshold !== null && entry.severity_level < threshold)
            return false;
        if (needle === "")
            return true;
        return entry.name.toLowerCase().includes(needle) ||
               entry.path.toLowerCase().includes(needle) ||
               entry.message.toLowerCase().includes(needle);
    };

    // Returns whether anything in this subtree is visible, so the caller can
    // decide whether to keep itself as the path to a hit.
    const walk = (entry: DiagnosticsEntry): boolean => {
        const childVisible = entry.children
                .map(walk)
                .some(Boolean);
        const self = matchesSelf(entry);

        if (self)
            matches += 1;

        if (self || childVisible) {
            visible.add(entry.rawName);
            if (childVisible)
                expand.add(entry.rawName);
            return true;
        }
        return false;
    };

    entries.forEach(walk);
    return { visible, expand, matches };
};
```

Achtung bei `walk`: `.map(walk).some(Boolean)` statt `.some(walk)` — `some` bricht beim ersten Treffer ab und würde die restlichen Geschwister nie besuchen, wodurch deren Sichtbarkeit fehlte.

- [ ] **Schritt 4: Test laufen lassen, Erfolg bestätigen**

Ausführen: `node test/unit/run.js treefilter`
Erwartet: PASS — `treeFilter: OK (ancestors kept, case-insensitive, stale in both levels, AND)`

- [ ] **Schritt 5: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck
```

---

## Task 5: Kopfband

**Files:**
- Create: `src/components/StatusBand.tsx`
- Modify: `src/app.tsx`, `src/app.scss`, `po/de.po`
- Test: `test/unit/components.test.ts` (erweitern)

**Interfaces:**
- Consumes: `summarise`, `headline`, `updateRateHz` (Task 3), `SeverityIcon` (Task 1), `FilterLevel` (Task 4).
- Produces: `<StatusBand />` mit den Props aus Schritt 3. Task 10 hängt `menuItems` an, Task 9 nutzt `onFilterLevel`.

- [ ] **Schritt 1: Test erweitern**

An `test/unit/components.test.ts` vor dem `problems.length`-Block anfügen:

```ts
/* -------------------------------------------------------------- StatusBand */

import { StatusBand } from "../../src/components/StatusBand";
import { summarise } from "../../src/utils/summary";

const band = (over: Partial<React.ComponentProps<typeof StatusBand>> = {}) =>
    renderToStaticMarkup(React.createElement(StatusBand, {
        namespace: "/a200_0553",
        diagnostics: [],
        timestamp: null,
        bridgeConnected: true,
        rateHz: 1,
        isPaused: false,
        onTogglePause: () => undefined,
        onFilterLevel: () => undefined,
        menuItems: null,
        ...over,
    }));

const healthy = band();
check(healthy.includes("operational"), "an empty tree reads as operational");
check(healthy.includes("/a200_0553"), "the namespace is shown");
check(!healthy.includes("Bridge disconnected"), "a connected bridge is not announced as disconnected");

check(band({ bridgeConnected: false }).includes("Bridge disconnected"),
      "a missing bridge is stated in the band, not only in the empty tree");

// Counts must come from the leaves of the real capture, not from the statuses.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const realTree = buildDiagnosticsTree(live as any[]);
const withData = band({ diagnostics: realTree });
check(withData.includes("1 warning"), "the band states the warning from the capture");
check(summarise(realTree).total === 15, "and counts 15 statuses");
```

Dazu oben im Test die Importe für `buildDiagnosticsTree` und `live` ergänzen:

```ts
import live from "./agg-armed.json";
import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: FAIL — `Could not resolve "../../src/components/StatusBand"`

- [ ] **Schritt 3: Die Komponente schreiben**

`src/components/StatusBand.tsx` (Lizenzkopf wie oben):

```tsx
import React from 'react';
import {
    Button,
    Dropdown,
    DropdownList,
    Flex,
    FlexItem,
    MenuToggle,
    MenuToggleElement,
} from "@patternfly/react-core";
import { EllipsisVIcon, PauseIcon, PlayIcon } from "@patternfly/react-icons";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { FilterLevel } from "../utils/treeFilter";
import { SeverityIcon } from "./SeverityIcon";
import { headline, summarise } from "../utils/summary";

const _ = cockpit.gettext;

/*
 * The band answers "is the robot fine?" without scrolling.
 *
 * Everything in here is derived, never stored: the sentence, the counters and
 * the worst level all come out of the tree that is currently on display -- which
 * on a frozen timeline is a past snapshot, not the live one. That is also why
 * the timestamp shown is the snapshot's and not the wall clock.
 */

const Kpi = ({
    value,
    label,
    onClick,
}: {
    value: number,
    label: string,
    onClick?: () => void,
}) => {
    // A counter at zero is not a filter anybody wants: clicking "0 errors" would
    // still open a threshold that lists stale messages.
    const clickable = onClick !== undefined && value > 0;
    const body = (
        <>
            <b className={value > 0 ? "status-kpi-value status-kpi-hit" : "status-kpi-value"}>{value}</b>
            <span className="status-kpi-label">{label}</span>
        </>
    );

    if (!clickable) {
        return <div className="status-kpi">{body}</div>;
    }
    return (
        <Button variant="plain" className="status-kpi" onClick={onClick} aria-label={label}>
            {body}
        </Button>
    );
};

export const StatusBand = ({
    namespace,
    diagnostics,
    timestamp,
    bridgeConnected,
    rateHz,
    isPaused,
    onTogglePause,
    onFilterLevel,
    menuItems,
}: {
    namespace: string,
    diagnostics: DiagnosticsEntry[],
    timestamp: number | null,
    bridgeConnected: boolean,
    rateHz: number | null,
    isPaused: boolean,
    onTogglePause: () => void,
    onFilterLevel: (level: FilterLevel) => void,
    menuItems: React.ReactNode,
}) => {
    const [menuOpen, setMenuOpen] = React.useState(false);
    const summary = summarise(diagnostics);

    const facts = [
        namespace,
        bridgeConnected ? _("Bridge connected") : _("Bridge disconnected"),
        rateHz !== null ? cockpit.format(_("$0 Hz"), rateHz.toFixed(1)) : null,
        timestamp !== null
            ? cockpit.format(_("as of $0"), new Date(timestamp).toLocaleTimeString())
            : null,
    ].filter(Boolean);

    return (
        <div className="status-band">
            <Flex
                justifyContent={{ default: 'justifyContentSpaceBetween' }}
                alignItems={{ default: 'alignItemsFlexStart' }}
            >
                <FlexItem>
                    <h1 className="status-headline">
                        <SeverityIcon level={summary.worst} />
                        {" "}
                        {namespace.replace(/^\//, "")}
                        {" — "}
                        <span className="status-headline-state">{headline(summary)}</span>
                    </h1>
                    <div className="status-facts">{facts.join(" · ")}</div>
                </FlexItem>
                <FlexItem>
                    <Flex
                        alignItems={{ default: 'alignItemsCenter' }}
                        spaceItems={{ default: 'spaceItemsLg' }}
                    >
                        <Kpi value={summary.errors} label={_("Errors")} onClick={() => onFilterLevel("error")} />
                        <Kpi value={summary.warnings} label={_("Warnings")} onClick={() => onFilterLevel("warn")} />
                        <Kpi value={summary.stale} label={_("Stale")} />
                        <Kpi value={summary.total} label={_("Statuses")} />
                        <FlexItem>
                            <Button
                                variant="secondary"
                                icon={isPaused ? <PlayIcon /> : <PauseIcon />}
                                onClick={onTogglePause}
                                aria-label={isPaused ? _("Resume diagnostics updates") : _("Pause diagnostics updates")}
                            >
                                {isPaused ? _("Resume") : _("Pause")}
                            </Button>
                        </FlexItem>
                        <FlexItem>
                            <Dropdown
                                isOpen={menuOpen}
                                onOpenChange={setMenuOpen}
                                popperProps={{ position: 'right' }}
                                toggle={(ref: React.Ref<MenuToggleElement>) => (
                                    <MenuToggle
                                        ref={ref}
                                        variant="plain"
                                        aria-label={_("More actions")}
                                        onClick={() => setMenuOpen(!menuOpen)}
                                        isExpanded={menuOpen}
                                    >
                                        <EllipsisVIcon />
                                    </MenuToggle>
                                )}
                            >
                                <DropdownList>{menuItems}</DropdownList>
                            </Dropdown>
                        </FlexItem>
                    </Flex>
                </FlexItem>
            </Flex>
        </div>
    );
};
```

- [ ] **Schritt 4: SCSS-Grundlage anlegen**

An `src/app.scss` anhängen:

```scss
/* Status band ------------------------------------------------------------- */

.status-band {
    position: sticky;
    inset-block-start: 0;
    z-index: 10;
    padding: var(--pf-t--global--spacer--md) var(--pf-t--global--spacer--lg) 0;
    background: var(--pf-t--global--background--color--primary--default);
    border-block-end: 1px solid var(--pf-t--global--border--color--default);
}

.status-headline {
    font-size: var(--pf-t--global--font--size--lg);
    font-weight: var(--pf-t--global--font--weight--heading--default);
    margin: 0;
}

.status-headline-state {
    font-weight: var(--pf-t--global--font--weight--body--default);
}

.status-facts {
    color: var(--pf-t--global--text--color--subtle);
    font-size: var(--pf-t--global--font--size--sm);
    margin-block-start: var(--pf-t--global--spacer--xs);
}

.status-kpi {
    text-align: end;
    min-inline-size: 3.5rem;
}

.status-kpi-value {
    display: block;
    font-size: var(--pf-t--global--font--size--2xl);
    font-weight: var(--pf-t--global--font--weight--body--default);
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    opacity: 0.85;
}

/* Only a counter that is not zero earns emphasis. */
.status-kpi-hit {
    opacity: 1;
    font-weight: var(--pf-t--global--font--weight--heading--default);
}

.status-kpi-label {
    font-size: var(--pf-t--global--font--size--xs);
    color: var(--pf-t--global--text--color--subtle);
}

/* An out-of-service subsystem is not a fault; its symbol must not shout. */
.severity-icon-inactive {
    color: var(--pf-t--global--icon--color--subtle);
}
```

- [ ] **Schritt 5: In `app.tsx` einhängen**

In `src/app.tsx` den bisherigen `Flex`-Block mit `Title` und Pause-Button (Zeilen 75–94) durch das Kopfband ersetzen. Die restliche Struktur bleibt für den Moment, wie sie ist:

```tsx
<StatusBand
    namespace={namespace}
    diagnostics={diagnostics}
    timestamp={diagStatusDisplay?.timestamp ?? null}
    bridgeConnected={bridgeConnected}
    rateHz={updateRateHz(diagHistory)}
    isPaused={isPaused}
    onTogglePause={() => {
        if (isPaused) clearDiagHistory();
        setIsPaused(!isPaused);
    }}
    onFilterLevel={() => undefined}
    menuItems={null}
/>
```

Importe ergänzen: `StatusBand` und `updateRateHz`; die nun unbenutzten Importe `Button`, `Title`, `PauseIcon`, `PlayIcon` entfernen — `make codecheck` benennt sie.

`onFilterLevel` bleibt bis Task 9 ein Platzhalter ohne Wirkung, `menuItems` bis Task 10 `null`. Beides ist beabsichtigt und in den jeweiligen Aufgaben abgeschlossen.

- [ ] **Schritt 6: Test laufen lassen, Erfolg bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: PASS

- [ ] **Schritt 7: Übersetzungen ergänzen**

In `po/de.po`: `Bridge connected`→`Bridge verbunden`, `Bridge disconnected`→`Bridge getrennt`, `$0 Hz`→`$0 Hz`, `as of $0`→`Stand $0`, `Errors`→`Fehler`, `Warnings`→`Warnungen`, `Stale`→`Veraltet`, `Statuses`→`Stati`, `More actions`→`Weitere Aktionen`. Bereits vorhandene `msgid`s (`Pause`, `Resume`, …) nicht doppeln.

- [ ] **Schritt 8: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Erwartet: alle grün, `dist/` baut durch.

---

## Task 6: Zeitachse

**Files:**
- Create: `src/components/Timeline.tsx`
- Delete: `src/components/HistorySelection.tsx`
- Modify: `src/app.tsx`, `src/app.scss`, `po/de.po`

**Interfaces:**
- Consumes: `HISTORY_SIZE` aus `hooks/useDiagHistory`, `headline`/`summarise` (Task 3).
- Produces: `<Timeline />` mit denselben Props, die `HistorySelection` heute hat (`diagHistory`, `setDiagStatusDisplay`, `isPaused`, `setIsPaused`) — die Historien-Verdrahtung bleibt damit unverändert.

- [ ] **Schritt 1: Die Komponente schreiben**

`src/components/Timeline.tsx` (Lizenzkopf wie oben, zusätzlich die Clearpath-Zeile übernehmen, weil die Auswahl-Logik aus `HistorySelection.tsx` stammt):

```tsx
import React, { useEffect, useState } from 'react';

import cockpit from 'cockpit';

import { DiagnosticsStatus } from "../interfaces";
import { HISTORY_SIZE } from '../hooks/useDiagHistory';
import { LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN } from '../utils/severity';

const _ = cockpit.gettext;

/*
 * The retained snapshots as one band.
 *
 * Equal-height segments on purpose: varying heights read as a chart and invite
 * comparison of a quantity that does not exist here. Colour marks the snapshots
 * worth clicking; everything healthy stays neutral grey.
 *
 * Unfilled slots are rendered on the left so the newest snapshot always ends at
 * the right edge and the band keeps its width while the history fills up.
 */
const variantFor = (level: number): string => {
    if (level >= LEVEL_STALE) return "stale";
    if (level >= LEVEL_ERROR) return "error";
    if (level >= LEVEL_WARN) return "warn";
    return "ok";
};

export const Timeline = ({
    diagHistory,
    setDiagStatusDisplay,
    isPaused,
    setIsPaused,
}: {
    diagHistory: DiagnosticsStatus[],
    setDiagStatusDisplay: React.Dispatch<React.SetStateAction<DiagnosticsStatus | null>>,
    isPaused: boolean,
    setIsPaused: React.Dispatch<React.SetStateAction<boolean>>,
}) => {
    // -1 is the latest, -2 the one before it, ... (kept from HistorySelection).
    const [negIndex, setNegIndex] = useState(-1);

    useEffect(() => {
        if (!isPaused) {
            setNegIndex(-1);
            setDiagStatusDisplay(diagHistory.length > 0 ? diagHistory[diagHistory.length - 1] : null);
        }
    }, [diagHistory, setDiagStatusDisplay, isPaused]);

    const blanks = Math.max(0, HISTORY_SIZE - diagHistory.length);
    const selected = diagHistory.length + negIndex;

    return (
        <div className="timeline">
            <div className="timeline-band" role="group" aria-label={_("Diagnostics history")}>
                {Array.from({ length: blanks }).map((_unused, index) => (
                    <span key={`blank-${index}`} className="timeline-slot timeline-slot-empty" />
                ))}
                {diagHistory.map((snapshot, index) => (
                    <button
                        type="button"
                        key={index}
                        className={`timeline-slot timeline-slot-${variantFor(snapshot.level)}` +
                                   (isPaused && index === selected ? " timeline-slot-selected" : "")}
                        title={new Date(snapshot.timestamp).toLocaleTimeString()}
                        aria-label={cockpit.format(_("diagnostics snapshot $0"), index + 1)}
                        onClick={() => {
                            setDiagStatusDisplay(snapshot);
                            setIsPaused(true);
                            setNegIndex(index - diagHistory.length);
                        }}
                    />
                ))}
            </div>
            <div className="timeline-legend">
                <span>{diagHistory.length > 0
                    ? new Date(diagHistory[0].timestamp).toLocaleTimeString()
                    : _("no history yet")}
                </span>
                <span>{cockpit.format(_("$0 snapshots · click to freeze"), HISTORY_SIZE)}</span>
                <span>{isPaused ? _("frozen") : _("now")}</span>
            </div>
        </div>
    );
};
```

- [ ] **Schritt 2: SCSS ergänzen**

An `src/app.scss` anhängen:

```scss
/* Timeline ---------------------------------------------------------------- */

.timeline {
    padding-block: var(--pf-t--global--spacer--sm) var(--pf-t--global--spacer--md);
}

.timeline-band {
    display: flex;
    gap: 2px;
    block-size: 0.625rem;
}

.timeline-slot {
    flex: 1;
    border: none;
    border-radius: 1px;
    padding: 0;
    background: var(--pf-t--global--color--nonstatus--gray--default);
}

.timeline-slot-empty {
    opacity: 0.25;
}

.timeline-slot-ok {
    opacity: 0.55;
}

.timeline-slot-warn {
    background: var(--pf-t--global--color--status--warning--default);
}

.timeline-slot-error {
    background: var(--pf-t--global--color--status--danger--default);
}

.timeline-slot-stale {
    background: var(--pf-t--global--color--status--info--default);
}

.timeline-slot-selected {
    outline: 1px solid var(--pf-t--global--border--color--default);
    outline-offset: 1px;
}

.timeline-legend {
    display: flex;
    justify-content: space-between;
    font-size: var(--pf-t--global--font--size--xs);
    color: var(--pf-t--global--text--color--subtle);
    margin-block-start: var(--pf-t--global--spacer--xs);
}
```

Sollte ein Tokenname von Stylelint oder zur Laufzeit nicht aufgelöst werden, den tatsächlichen Namen aus `node_modules/@patternfly/patternfly/base/` nachschlagen — **nicht** durch einen Hex-Wert ersetzen.

- [ ] **Schritt 3: Einhängen und Altkomponente entfernen**

In `src/app.tsx` `<HistorySelection … />` durch `<Timeline … />` mit identischen Props ersetzen, den Import umstellen, dann `src/components/HistorySelection.tsx` löschen.

Das Kopfband ist sticky; die Zeitachse gehört optisch dazu und wandert deshalb **in** den `.status-band`-Container, direkt unter das `Flex`-Element in `StatusBand`. Dazu bekommt `StatusBand` ein zusätzliches Prop `children: React.ReactNode`, das nach dem `Flex` gerendert wird, und `app.tsx` reicht die `Timeline` als Kind hinein:

```tsx
<StatusBand … >
    <Timeline
        diagHistory={diagHistory}
        setDiagStatusDisplay={setDiagStatusDisplay}
        isPaused={isPaused}
        setIsPaused={setIsPaused}
    />
</StatusBand>
```

In `StatusBand.tsx` das Prop ergänzen und nach dem schließenden `</Flex>` einfügen: `{children}`.

Das Prop muss **optional** deklariert werden (`children?: React.ReactNode`), sonst wird der in Task 5 geschriebene Test ungültig, der `StatusBand` ohne Kinder rendert. Wegen `exactOptionalPropertyTypes` darf es nirgends explizit `undefined` bekommen — einfach weglassen, wo keine Kinder gebraucht werden.

- [ ] **Schritt 4: Übersetzungen ergänzen**

`no history yet`→`noch kein Verlauf`, `$0 snapshots · click to freeze`→`$0 Schnappschüsse · Klick friert ein`, `frozen`→`eingefroren`, `now`→`jetzt`, `Diagnostics history`→`Diagnoseverlauf`. `diagnostics snapshot $0` existiert bereits aus `HistorySelection`.

- [ ] **Schritt 5: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Erwartet: alle grün; `grep -r HistorySelection src/` liefert nichts mehr.

---

## Task 7: Auffälligkeitenliste

**Files:**
- Create: `src/components/IssueList.tsx`
- Delete: `src/components/DiagnosticsTable.tsx`
- Modify: `src/app.tsx`, `src/app.scss`, `po/de.po`
- Test: `test/unit/components.test.ts` (erweitern)

**Interfaces:**
- Consumes: `issueEntries` (Task 3), `SeverityIcon` (Task 1).
- Produces: `<IssueList diagnostics={…} setSelectedRawName={…} />`

- [ ] **Schritt 1: Test erweitern**

An `test/unit/components.test.ts` anfügen:

```ts
/* ---------------------------------------------------------------- IssueList */

import { IssueList } from "../../src/components/IssueList";

const issueMarkup = (entries: DiagnosticsEntry[]) =>
    renderToStaticMarkup(React.createElement(IssueList, {
        diagnostics: entries,
        setSelectedRawName: () => undefined,
    }));

const realIssues = issueMarkup(realTree);
check(realIssues.includes("Hardware Components Activity"), "the warning is listed");
check(!realIssues.includes("Joystick Driver Status"),
      "an out-of-service status is not an issue to act on");

// The old pair of tables claimed "No Errors" / "No Warnings" even while the
// bridge was down. One quiet line, and only when there is genuinely nothing.
const empty = issueMarkup([]);
check(empty.includes("No issues"), "an empty list is one line, not an empty state");
check(!empty.includes("<table"), "an empty list renders no table");
```

Dazu den Import `import { DiagnosticsEntry } from "../../src/interfaces";` oben ergänzen.

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: FAIL — `Could not resolve "../../src/components/IssueList"`

- [ ] **Schritt 3: Die Komponente schreiben**

`src/components/IssueList.tsx` (Lizenzkopf wie oben):

```tsx
import React from 'react';
import { Table, Tbody, Td, Tr } from "@patternfly/react-table";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { SeverityIcon } from "./SeverityIcon";
import { issueEntries } from "../utils/summary";

const _ = cockpit.gettext;

/*
 * Everything worth acting on, in one list.
 *
 * Replaces the pair of alert-wrapped tables (errors, warnings) that each cost a
 * full empty state even when there was nothing to show -- and that reported
 * "No Errors" while the bridge was down, which was not the same thing at all.
 */
export const IssueList = ({
    diagnostics,
    setSelectedRawName,
}: {
    diagnostics: DiagnosticsEntry[],
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const issues = issueEntries(diagnostics);

    if (issues.length === 0) {
        return <div className="issue-empty">{_("No issues")}</div>;
    }

    return (
        <Table aria-label={_("Issues")} borders={false} variant="compact" className="issue-list">
            <Tbody>
                {issues.map(issue => (
                    <Tr key={issue.rawName} isClickable onRowClick={() => setSelectedRawName(issue.rawName)}>
                        <Td className="issue-level" modifier="fitContent">
                            <SeverityIcon level={issue.severity_level} hideOk />
                        </Td>
                        <Td>
                            <span className="diagnostics-table-name">{issue.name || _("N/A")}</span>
                            <div className="issue-path">{issue.path || _("N/A")}</div>
                        </Td>
                        <Td>{issue.message || _("N/A")}</Td>
                    </Tr>
                ))}
            </Tbody>
        </Table>
    );
};
```

- [ ] **Schritt 4: SCSS ergänzen**

```scss
/* Issue list -------------------------------------------------------------- */

.issue-empty {
    color: var(--pf-t--global--text--color--subtle);
    padding-block: var(--pf-t--global--spacer--sm);
}

.issue-path {
    font-size: var(--pf-t--global--font--size--xs);
    color: var(--pf-t--global--text--color--subtle);
}
```

- [ ] **Schritt 5: Einhängen und Altkomponente entfernen**

In `src/app.tsx` beide `<DiagnosticsTable … variant="error" />` und `… variant="warning" />` durch **eine** Instanz ersetzen:

```tsx
<IssueList diagnostics={diagnostics} setSelectedRawName={setSelectedRawName} />
```

Die umgebende Bedingung `diagnostics.length > 0 && (…)` bleibt vorerst bestehen; Task 11 ordnet den Block endgültig ein. Import umstellen, dann `src/components/DiagnosticsTable.tsx` löschen.

- [ ] **Schritt 6: Test laufen lassen, Erfolg bestätigen**

Ausführen: `node test/unit/run.js components`
Erwartet: PASS

- [ ] **Schritt 7: Übersetzungen ergänzen**

`No issues`→`Keine Auffälligkeiten`, `Issues`→`Auffälligkeiten`.

- [ ] **Schritt 8: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Erwartet: grün; `grep -r DiagnosticsTable src/ | grep -v TreeTable` liefert nichts mehr.

---

## Task 8: Detail-Panel auf Seitenebene

**Files:**
- Create: `src/components/DetailPanel.tsx`
- Modify: `src/components/DiagnosticsTreeTable.tsx`, `src/app.tsx`, `po/de.po`

**Interfaces:**
- Consumes: `SeverityIcon` (Task 1).
- Produces:
  - `<DetailPanel entry={DiagnosticsEntry | null} onClose={() => void} />` — der Inhalt des Drawers.
  - `findEntryByRawName(entries, rawName): DiagnosticsEntry | null` wird aus `DiagnosticsTreeTable` nach `DetailPanel.tsx` verschoben und dort exportiert, damit `app.tsx` den ausgewählten Eintrag auflösen kann.

Warum der Umzug: alle drei Auswahlquellen — Auffälligkeitenliste, Manipulator-Meldung, Baumzeile — rufen bereits dieselbe Funktion `setSelectedRawName` auf, aber der Drawer steckte in der Baum-Karte und war auf 35 % von deren Breite begrenzt. In der rechten Spalte von Task 11 wäre das ein Briefschlitz.

- [ ] **Schritt 1: `DetailPanel.tsx` anlegen**

```tsx
import React from 'react';
import {
    DescriptionList,
    DescriptionListDescription,
    DescriptionListGroup,
    DescriptionListTerm,
    DrawerActions,
    DrawerCloseButton,
    DrawerHead,
    DrawerPanelBody,
    Title,
} from "@patternfly/react-core";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { SeverityIcon, severityLabel } from "./SeverityIcon";

const _ = cockpit.gettext;

// Moved here from DiagnosticsTreeTable: the selection now lives on the page, so
// whoever renders the panel has to be able to resolve a rawName.
export const findEntryByRawName = (
    entries: DiagnosticsEntry[],
    rawName: string,
): DiagnosticsEntry | null => {
    for (const entry of entries) {
        if (entry.rawName === rawName)
            return entry;
        const found = findEntryByRawName(entry.children, rawName);
        if (found)
            return found;
    }
    return null;
};

const Term = ({ label, children }: { label: string, children: React.ReactNode }) => (
    <DescriptionListGroup>
        <DescriptionListTerm>{label}</DescriptionListTerm>
        <DescriptionListDescription>{children}</DescriptionListDescription>
    </DescriptionListGroup>
);

export const DetailPanel = ({
    entry,
    onClose,
}: {
    entry: DiagnosticsEntry | null,
    onClose: () => void,
}) => {
    const panelRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        if (entry && panelRef.current)
            panelRef.current.focus();
    }, [entry]);

    if (!entry) {
        return null;
    }

    return (
        <>
            <DrawerHead>
                <Title headingLevel="h2" size="md">
                    <SeverityIcon level={entry.severity_level} /> {severityLabel(entry.severity_level)}
                </Title>
                <DrawerActions>
                    <DrawerCloseButton onClick={onClose} />
                </DrawerActions>
            </DrawerHead>
            <DrawerPanelBody>
                <div tabIndex={0} ref={panelRef} className="detail-body">
                    <Title headingLevel="h3" size="md">{entry.name}</Title>
                    <div className="detail-path">{entry.path}</div>
                    <p className="detail-message">{entry.message || _("No message")}</p>
                    <DescriptionList isHorizontal isCompact>
                        <Term label={_("Hardware ID")}>{entry.hardware_id || _("N/A")}</Term>
                        {/*
                          * A reclassified status must never look like the original:
                          * show what ROS actually reported and why it is displayed
                          * differently.
                          */}
                        {entry.override_reason && (
                            <Term label={_("Reported level")}>
                                {severityLabel(entry.reported_level)}
                                {" — "}
                                {_(entry.override_reason)}
                            </Term>
                        )}
                    </DescriptionList>
                    {entry.values && Object.keys(entry.values).length > 0 && (
                        <>
                            <Title headingLevel="h4" size="md" className="detail-values-title">
                                {_("Values")}
                            </Title>
                            <DescriptionList isHorizontal isCompact className="detail-values">
                                {Object.entries(entry.values).map(([key, value]) => (
                                    <Term key={key} label={key}>{String(value)}</Term>
                                ))}
                            </DescriptionList>
                        </>
                    )}
                </div>
            </DrawerPanelBody>
        </>
    );
};
```

- [ ] **Schritt 2: Drawer aus dem Baum entfernen**

In `src/components/DiagnosticsTreeTable.tsx`:

- alle `Drawer*`-Importe, `drawerPanel`, `drawerRef`, `triggerDrawerFocus`, `closeDrawer`, `findEntryByRawName`, `selectedEntry` und die zugehörigen `useEffect`s entfernen,
- der Rückgabewert reduziert sich auf die `Card` mit der `Table` (der `Drawer`-Rahmen fällt weg),
- die Auto-Aufklapp-Logik (`findPathToRawName` + zugehöriger `useEffect`) **bleibt**: sie klappt die Vorfahren eines von außen ausgewählten Status auf und ist unabhängig vom Drawer.

- [ ] **Schritt 3: Drawer in `app.tsx` mounten**

Die Arbeitsfläche wird vom `Drawer` umschlossen; `isExpanded` hängt an `selectedRawName`:

```tsx
const selectedEntry = selectedRawName ? findEntryByRawName(diagnostics, selectedRawName) : null;

// … innerhalb der PageSection:
<Drawer isExpanded={!!selectedEntry} onExpand={() => undefined}>
    <DrawerContent
        panelContent={
            <DrawerPanelContent isResizable defaultSize="28rem" minSize="20rem">
                <DetailPanel entry={selectedEntry} onClose={() => setSelectedRawName(null)} />
            </DrawerPanelContent>
        }
    >
        <DrawerContentBody>
            {/* Arbeitsfläche: IssueList, ManipulatorPanel, DiagnosticsTreeTable */}
        </DrawerContentBody>
    </DrawerContent>
</Drawer>
```

`isInline` **muss** gesetzt werden — die ursprüngliche Vorgabe hier war falsch.

Ohne `isInline` bekommt der Drawer-Inhalt von PatternFly `flex: 0 0 100%`, kann also
nicht schrumpfen, während das Panel in derselben Flex-Reihe seine 336 px beansprucht.
Die Reihe läuft über, und weil sie beschneidet, wird der Inhalt um genau diese Breite
nach links aus dem Sichtfeld gedrückt (gemessen: −300 px, linke Werte unlesbar). Mit
`isInline` wird daraus `0 1 100%`, und das Panel nimmt seinen Platz vom Inhalt, statt
ihn hinauszuschieben. Am Roboter gemessen (2026-08-12).

Esc muss **selbst verdrahtet** werden. Ein PatternFly-Drawer schließt sich nicht von allein: `Drawer.js` hat überhaupt keinen Tastatur-Listener, der einzige Escape-Handler im Drawer-Paket sitzt im Resize-Splitter von `DrawerPanelContent`, und der `FocusTrap` greift nur, wenn das `focusTrap`-Prop gesetzt ist. Geprüft gegen PatternFly 6.4.0 (Task 8).

- [ ] **Schritt 4: SCSS ergänzen**

```scss
/* Detail panel ------------------------------------------------------------ */

.detail-path {
    font-size: var(--pf-t--global--font--size--xs);
    color: var(--pf-t--global--text--color--subtle);
    margin-block-end: var(--pf-t--global--spacer--sm);
}

.detail-message {
    background: var(--pf-t--global--background--color--secondary--default);
    border-radius: var(--pf-t--global--border--radius--small);
    padding: var(--pf-t--global--spacer--sm);
    margin-block-end: var(--pf-t--global--spacer--md);
}

.detail-values-title {
    margin-block-start: var(--pf-t--global--spacer--md);
    margin-block-end: var(--pf-t--global--spacer--sm);
}

.detail-values .pf-v6-c-description-list__description {
    font-variant-numeric: tabular-nums;
}

/*
 * On a narrow window a 28rem panel beside the content leaves neither of them
 * usable. Below the same breakpoint at which the workspace stops being two
 * columns, the panel covers the page instead.
 */
@media (width <= 1200px) {
    .pf-v6-c-drawer__panel {
        --pf-v6-c-drawer__panel--FlexBasis: 100%;
    }
}
```

PatternFly setzt die Panelbreite über die eigene Custom Property
`--pf-v6-c-drawer__panel--FlexBasis`, nicht über `inline-size`. Ein direktes
`inline-size: 100%` bleibt deshalb wirkungslos — die Regel greift, aber
`flex-basis` gewinnt und das Panel behält seine 28 rem. Empirisch gegen
PatternFly 6.4.0 im Browser geprüft (Task 8).

- [ ] **Schritt 5: Übersetzungen ergänzen**

`No message` existiert bereits (aus `ManipulatorPanel`). Neu: nichts — `Hardware ID`, `Values`, `N/A` stammen aus `DiagnosticsTreeTable` und sind vorhanden. Mit dem Skript aus Task 1 Schritt 5 gegenprüfen.

- [ ] **Schritt 6: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Erwartet: grün. Manuell (nach `make`, im Browser gegen einen laufenden Roboter oder gegen `foxglove`-Mock): Klick auf eine Auffälligkeit **und** auf eine Baumzeile öffnen beide dasselbe Panel; Esc und ✕ schließen es.

---

## Task 9: Level-Spalte, Suche und Filter im Baum

**Files:**
- Modify: `src/components/DiagnosticsTreeTable.tsx`, `src/app.tsx`, `src/app.scss`, `po/de.po`

**Interfaces:**
- Consumes: `filterTree`, `FilterLevel` (Task 4), `SeverityIcon` (Task 1).
- Produces: `DiagnosticsTreeTable` nimmt zusätzlich `query: string`, `filterLevel: FilterLevel`, `onQueryChange`, `onFilterLevelChange`.

- [ ] **Schritt 1: Zustand in `app.tsx` anlegen**

```tsx
const [query, setQuery] = useState("");
const [filterLevel, setFilterLevel] = useState<FilterLevel>("all");
```

Und das Kopfband verdrahten — der Platzhalter aus Task 5 wird ersetzt:

```tsx
onFilterLevel={setFilterLevel}
```

- [ ] **Schritt 2: Kopfzeile mit Suche und Filter in den Baum einbauen**

In `DiagnosticsTreeTable.tsx` die `CardTitle` durch Titel plus Bedienzeile ersetzen:

```tsx
<CardTitle component="h2" className="diagnostics-title">{_("All Diagnostics")}</CardTitle>
<CardBody>
    <div className="tree-controls">
        <SearchInput
            value={query}
            onChange={(_event, value) => onQueryChange(value)}
            onClear={() => onQueryChange("")}
            placeholder={_("Search name, path or message")}
            aria-label={_("Search diagnostics")}
        />
        <ToggleGroup aria-label={_("Severity filter")}>
            <ToggleGroupItem
                text={_("All")}
                isSelected={filterLevel === "all"}
                onChange={() => onFilterLevelChange("all")}
            />
            <ToggleGroupItem
                text={_("≥ Warning")}
                isSelected={filterLevel === "warn"}
                onChange={() => onFilterLevelChange("warn")}
            />
            <ToggleGroupItem
                text={_("≥ Error")}
                isSelected={filterLevel === "error"}
                onChange={() => onFilterLevelChange("error")}
            />
        </ToggleGroup>
    </div>
    …
```

Importe ergänzen: `SearchInput`, `ToggleGroup`, `ToggleGroupItem` aus `@patternfly/react-core`.

- [ ] **Schritt 3: Filter anwenden und Level-Spalte einziehen**

In `DiagnosticsTreeTable`:

```tsx
const { visible, expand, matches } = filterTree(diagnostics, query, filterLevel);
```

`renderRows` bekommt eine zusätzliche Bedingung ganz am Anfang — nicht sichtbare Knoten werden übersprungen, ihre Geschwister aber weiter verarbeitet:

```tsx
if (!visible.has(diag.rawName)) {
    return renderRows(remainingDiag, indentLevel, posinset, rowIndex, isHidden);
}
```

Der Aufklappzustand berücksichtigt zusätzlich die erzwungene Menge:

```tsx
const isExpanded = expandedRows.includes(diag.rawName) || expand.has(diag.rawName);
```

Die Level-Spalte wird zur ersten Spalte. Im `Thead`:

```tsx
<Th screenReaderText={_("Level")} className="tree-level" />
<Th>{_("Name")}</Th>
<Th>{_("Message")}</Th>
```

Und in der Zeile **vor** der Namenszelle:

```tsx
<Td dataLabel={_("Level")} className="tree-level">
    <SeverityIcon level={diag.severity_level} hideOk />
</Td>
```

`colSpan` des leeren Zustands von 2 auf 3 erhöhen.

- [ ] **Schritt 4: Leeres Filterergebnis behandeln**

Wenn `diagnostics.length > 0 && matches === 0`, statt der Tabellenzeilen:

```tsx
<Tr>
    <Td colSpan={3}>
        <Bullseye>
            <EmptyState headingLevel="h2" titleText={_("Nothing matches")} variant={EmptyStateVariant.xs}>
                <EmptyStateBody>
                    <Button
                        variant="link"
                        isInline
                        onClick={() => {
                            onQueryChange("");
                            onFilterLevelChange("all");
                        }}
                    >
                        {_("Reset filters")}
                    </Button>
                </EmptyStateBody>
            </EmptyState>
        </Bullseye>
    </Td>
</Tr>
```

`Button` aus `@patternfly/react-core` importieren.

- [ ] **Schritt 5: SCSS ergänzen**

```scss
/* Tree controls ----------------------------------------------------------- */

.tree-controls {
    display: flex;
    gap: var(--pf-t--global--spacer--sm);
    align-items: center;
    margin-block-end: var(--pf-t--global--spacer--md);
    flex-wrap: wrap;
}

.tree-controls .pf-v6-c-text-input-group {
    flex: 1;
    min-inline-size: 12rem;
}

/*
 * The column keeps its width even while every row in view is OK, so switching
 * the filter does not shift the names sideways.
 */
.tree-level {
    inline-size: 1.75rem;
}
```

- [ ] **Schritt 6: Übersetzungen ergänzen**

`Search name, path or message`→`Name, Pfad oder Meldung durchsuchen`, `Search diagnostics`→`Diagnosen durchsuchen`, `Severity filter`→`Schweregrad-Filter`, `All`→`Alle`, `≥ Warning`→`≥ Warnung`, `≥ Error`→`≥ Fehler`, `Nothing matches`→`Kein Treffer`, `Reset filters`→`Filter zurücksetzen`, `Level`→`Level`.

- [ ] **Schritt 7: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Manuell: Suche nach `imu` blendet fremde Zweige aus und klappt den Pfad zum Treffer auf; Umschalten auf `≥ Fehler` behält veraltete Meldungen; Klick auf die Kennzahl „Warnungen“ im Kopfband setzt den Umschalter auf `≥ Warnung`; eine Kennzahl mit Wert 0 ist nicht anklickbar.

---

## Task 10: Capture ins ⋯-Menü

**Files:**
- Modify: `src/components/DiagnosticsCapture.tsx`, `src/app.tsx`, `po/de.po`

**Interfaces:**
- Consumes: `StatusBand`-Prop `menuItems` (Task 5).
- Produces:
  - `useCapture(namespace): { isCapturing, errorMessage, downloadPath, adminAccess, capture }` — die vorhandene Logik, unverändert, nur aus der Komponente herausgehoben.
  - `<CaptureAlerts state={…} />` — Fortschritt, Fehler und Download-Link.

Beide bleiben in `DiagnosticsCapture.tsx`: die Datei behält damit genau eine Verantwortung (Diagnose-Paket), und der Auslöser kann trotzdem im Menü sitzen.

- [ ] **Schritt 1: Logik zum Hook umbauen**

In `src/components/DiagnosticsCapture.tsx` die bisherige Komponente in einen Hook überführen. `useState`, `useEffect` (Berechtigung), `runBash` und `handleCapture` wandern unverändert hinein; nur die Rückgabe ändert sich:

```tsx
export interface CaptureState {
    isCapturing: boolean;
    errorMessage: string | null;
    downloadPath: string | null;
    adminAccess: boolean;
    capture: () => Promise<void>;
}

export const useCapture = (namespace: string): CaptureState => {
    // … unveränderter Rumpf der bisherigen Komponente bis einschließlich handleCapture …
    return { isCapturing, errorMessage, downloadPath, adminAccess, capture: handleCapture };
};
```

Die Befehlslisten `commands_su`, `commands_usr`, `commands_clearpath`, die Redaktion der netplan-Passwörter und die Archivbenennung bleiben **wortgleich**. Hier wird nichts umformuliert.

- [ ] **Schritt 2: Alerts als eigene Komponente**

```tsx
export const CaptureAlerts = ({ state }: { state: CaptureState }) => (
    <>
        {state.isCapturing && (
            <Alert
                variant="info"
                isInline
                title={_("Diagnostic capture may take several minutes to generate.")}
            />
        )}
        {!state.isCapturing && state.errorMessage && (
            <Alert variant="danger" isInline title={state.errorMessage} />
        )}
        {!state.isCapturing && state.downloadPath && (
            <Alert
                variant="success"
                isInline
                title={cockpit.format(_("Diagnostics captured successfully ($0)."), state.downloadPath)}
            >
                <Button variant="link" isInline onClick={() => downloadFile(state.downloadPath as string)}>
                    {_("Download Diagnostics File")}
                </Button>
            </Alert>
        )}
    </>
);
```

- [ ] **Schritt 3: Menüeintrag und Alerts in `app.tsx` einhängen**

```tsx
const capture = useCapture(namespace);

// … als menuItems an StatusBand:
menuItems={
    <DropdownItem
        key="capture"
        isDisabled={!capture.adminAccess || capture.isCapturing}
        description={!capture.adminAccess
            ? _("Enable admin access at the top of the page to enable diagnostics capture feature.")
            : undefined}
        onClick={() => { capture.capture() }}
    >
        {capture.isCapturing ? _("Generating…") : _("Generate diagnostics capture")}
    </DropdownItem>
}
```

Achtung `exactOptionalPropertyTypes`: `description` darf nicht explizit `undefined` bekommen. Stattdessen konditional streuen:

```tsx
{...(!capture.adminAccess
    ? { description: _("Enable admin access at the top of the page to enable diagnostics capture feature.") }
    : {})}
```

`<CaptureAlerts state={capture} />` direkt unter das Kopfband setzen, oberhalb der Arbeitsfläche. Die bisherige `<DiagnosticsCapture namespace={namespace} />`-Karte entfällt.

- [ ] **Schritt 4: Übersetzungen ergänzen**

`Generate diagnostics capture`→`Diagnose-Paket erzeugen`, `Generating…`→`Wird erzeugt…`. Die übrigen Zeichenketten sind bereits übersetzt.

- [ ] **Schritt 5: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Manuell auf dem Roboter: ohne Admin-Rechte ist der Menüpunkt deaktiviert und trägt den Hinweistext; mit Admin-Rechten erzeugt er ein Archiv unter `~/diagnostic_captures/` und der Download-Link erscheint unter dem Kopfband.

---

## Task 11: Zweispaltiges Layout

**Files:**
- Modify: `src/app.tsx`, `src/app.scss`

**Interfaces:**
- Consumes: alle Komponenten aus Tasks 5–10.
- Produces: die endgültige Seitenstruktur.

- [ ] **Schritt 1: `app.tsx` neu ordnen**

Der Rumpf innerhalb der `PageSection`:

```tsx
<StatusBand … >
    <Timeline … />
</StatusBand>

{invalidNamespaceMessage && <Alert variant="danger" isInline title={invalidNamespaceMessage} />}
{manualEntryRequired && <ManualNamespace setManualNamespace={setManualNamespace} namespace={namespace} />}
<CaptureAlerts state={capture} />

{!invalidNamespaceMessage && (
    <>
        <RosConnectionManager … />
        <Drawer isExpanded={!!selectedEntry}>
            <DrawerContent panelContent={…}>
                <DrawerContentBody>
                    {diagnostics.length === 0
                        ? <ConnectingState bridgeConnected={bridgeConnected} />
                        : (
                            <div className="workspace">
                                <div className="workspace-primary">
                                    <ManipulatorPanel … />
                                    <Card>
                                        <CardTitle component="h2" className="diagnostics-title">
                                            {_("Issues")}
                                        </CardTitle>
                                        <CardBody>
                                            <IssueList … />
                                        </CardBody>
                                    </Card>
                                </div>
                                <div className="workspace-secondary">
                                    <DiagnosticsTreeTable … />
                                </div>
                            </div>
                        )}
                </DrawerContentBody>
            </DrawerContent>
        </Drawer>
    </>
)}
```

`ConnectingState` ist der Leerzustand, der bisher **in** `DiagnosticsTreeTable` steckte. Er wandert nach `app.tsx` als kleine lokale Komponente, weil er jetzt für die ganze Arbeitsfläche gilt statt nur für den Baum:

```tsx
const ConnectingState = ({ bridgeConnected }: { bridgeConnected: boolean }) => (
    <Bullseye>
        <EmptyState headingLevel="h2" titleText={_("Connecting")} icon={Spinner} variant={EmptyStateVariant.sm}>
            <EmptyStateBody>
                {bridgeConnected
                    ? _("Waiting for diagnostics messages...")
                    : _("Attempting to connect to the Foxglove bridge...")}
            </EmptyStateBody>
        </EmptyState>
    </Bullseye>
);
```

Den entsprechenden Block in `DiagnosticsTreeTable` entfernen — die Tabelle wird nur noch mit Daten gerendert.

- [ ] **Schritt 2: SCSS für das Raster**

```scss
/* Workspace --------------------------------------------------------------- */

.workspace {
    display: grid;
    grid-template-columns: 1.05fr 1fr;
    gap: var(--pf-t--global--spacer--lg);
    align-items: start;
}

.workspace-primary {
    display: flex;
    flex-direction: column;
    gap: var(--pf-t--global--spacer--lg);
    min-inline-size: 0;
}

.workspace-secondary {
    min-inline-size: 0;
}

/*
 * Below this width two columns stop helping: the joint table and the tree both
 * need room for a name plus a path. Stack them, order unchanged.
 */
@media (width <= 1200px) {
    .workspace {
        grid-template-columns: 1fr;
    }
}
```

`min-inline-size: 0` ist nicht kosmetisch: ohne sie weigern sich Grid-Spalten zu schrumpfen, sobald eine Tabelle darin breiter wird, und die Seite bekommt einen horizontalen Scrollbalken.

- [ ] **Schritt 3: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Manuell: Fenster von 1600 px auf 900 px verkleinern — die Spalten stapeln bei 1200 px, kein horizontaler Scrollbalken; das Detail-Panel schiebt sich in beiden Breiten über die Arbeitsfläche.

---

## Task 12: Manipulator-Karten im neuen Stil

**Files:**
- Modify: `src/components/ManipulatorPanel.tsx`, `src/app.scss`, `test/unit/contract.test.ts`

**Interfaces:**
- Consumes: `SeverityIcon`, `severityLabel` (Task 1).
- Produces: keine neuen Signaturen — `ManipulatorPanel` behält seine Props.

**Kein Feld verschwindet.** Alle heute angezeigten Werte bleiben: Robot mode, Safety mode, External control, Motion link samt Hz, Controller-Anzahl und -Chips, Gelenktabelle mit Position (Grad und Radiant), Geschwindigkeit und Effort, sowie beim Greifer Öffnung, Griff, Bewegung, Werkzeugspannung, Kraftvorwahl, letztes Kommando und Kraftsignal.

- [ ] **Schritt 1: Doppelte Level-Zuordnung entfernen**

Die lokale `severityStyle`-Tabelle und die Komponente `SeverityLabel` in `ManipulatorPanel.tsx` löschen. Alle Verwendungsstellen ersetzen durch:

```tsx
<span className="card-state">
    <SeverityIcon level={level} /> {severityLabel(level)}
</span>
```

Die Importe `CheckCircleIcon`, `ExclamationCircleIcon`, `ExclamationTriangleIcon`, `OutlinedCircleIcon`, `QuestionCircleIcon`, `Label` und `LabelProps` entsprechend aufräumen — `Label` bleibt nur, soweit es noch für Controller-Chips gebraucht wird.

Die Hilfsfunktionen `modeColor`, `safetyColor`, `boolColor` und der Typ `LabelColor` entfallen: Robot mode, Safety mode, External control und Motion link werden künftig als schlichter Text dargestellt. Ihre Aussage steckt bereits im Zustand der Karte; ein zusätzlich eingefärbtes Etikett pro Zeile war genau die Mehrfachkodierung, die den ersten Entwurf unruhig gemacht hat. `boolText` bleibt.

- [ ] **Schritt 2: Karten auf Randstreifen umstellen**

`<Card isPlain isCompact>` in beiden Karten durch ein schlichtes `div` mit Zustandsklasse ersetzen:

```tsx
<div className={`state-card state-card-${cardVariant(level)}`}>
    <h3 className="state-card-title">
        {_("Arm")}
        <span className="card-state"><SeverityIcon level={level} /> {severityLabel(level)}</span>
    </h3>
    <div className="manipulator-subtitle">…</div>
    …
</div>
```

Mit einer lokalen Hilfsfunktion:

```tsx
// The stripe is the card's only state carrier; OK is deliberately grey, because
// "fine" is not something anybody scans for.
const cardVariant = (level: number): string => {
    if (level >= LEVEL_STALE) return "stale";
    if (level >= LEVEL_ERROR) return "error";
    if (level >= LEVEL_WARN) return "warn";
    return "quiet";
};
```

- [ ] **Schritt 3: Fortschrittsbalken entfärben**

Beim Greifer die `ProgressVariant.success`-Zuweisung entfernen und `ProgressVariant` aus dem Import streichen — der Balken misst eine Öffnung, er meldet keinen Zustand. Ob ein Objekt gehalten wird, steht weiterhin als Wert „Grip detected“ darunter.

- [ ] **Schritt 4: SCSS ergänzen**

```scss
/* State cards ------------------------------------------------------------- */

.state-card {
    border: 1px solid var(--pf-t--global--border--color--default);
    border-inline-start: 3px solid var(--pf-t--global--border--color--default);
    border-radius: var(--pf-t--global--border--radius--small);
    padding: var(--pf-t--global--spacer--md);
}

.state-card-warn {
    border-inline-start-color: var(--pf-t--global--color--status--warning--default);
}

.state-card-error {
    border-inline-start-color: var(--pf-t--global--color--status--danger--default);
}

.state-card-stale {
    border-inline-start-color: var(--pf-t--global--color--status--info--default);
}

.state-card-title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: var(--pf-t--global--font--size--md);
    margin: 0;
}

.card-state {
    display: inline-flex;
    align-items: center;
    gap: var(--pf-t--global--spacer--xs);
    font-size: var(--pf-t--global--font--size--sm);
    font-weight: var(--pf-t--global--font--weight--body--default);
    color: var(--pf-t--global--text--color--subtle);
}

/* Readings line up so they can be compared down the column. */
.manipulator-joints td,
.state-card .pf-v6-c-description-list__description {
    font-variant-numeric: tabular-nums;
}
```

- [ ] **Schritt 5: Vertrag nachziehen**

`test/unit/contract.test.ts` schürft Schlüsselliterale aus der Liste `SOURCES`. Sie bleibt gültig, solange die Schlüssel in `ManipulatorPanel.tsx` und `manipulatorUtils.ts` stehen. Prüfen, ob durch den Umbau ein `valueOf`/`boolOf`/`numberOf`-Aufruf in eine andere Datei gewandert ist; falls ja, diese Datei zu `SOURCES` hinzufügen — sonst prüft der Test stillschweigend weniger.

- [ ] **Schritt 6: Prüfen**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```
Erwartet: `contract` grün (das ist der Test, der einen umbenannten oder verlorenen Schlüssel fängt). Manuell: bei stromlosem Arm ist die Karte grau, die Werte gedimmt und die Erklärzeile sichtbar; bei fehlender Werkzeugspannung ist der Greifer-Randstreifen gelb.

---

## Task 13: Abschluss

**Files:**
- Modify: `test/check-application`, `po/de.po`, `README.md`

- [ ] **Schritt 1: Browser-Test anpassen**

In `test/check-application` wartet `enter_ros2_diagnostics` auf ein `h1` mit dem Text „ROS 2 Diagnostics“. Das Kopfband trägt jetzt Robotername und Zustandssatz. Anpassen auf die Klasse des Kopfbands:

```python
    def enter_ros2_diagnostics(self):
        self.login_and_go("/ros2-diagnostics")
        self.browser.wait_visible(".status-band")
```

Die zweite Zusicherung in `testBasic` — der Danger-Alert `'robot.yaml' file not found or empty` — bleibt **unverändert**: der Alert steht weiterhin unter dem Kopfband. Der Seitenname „ROS 2 diagnostics“ steht in `src/manifest.json` und damit in Cockpits Navigation; er geht nicht verloren.

- [ ] **Schritt 2: Übersetzungen vollständig prüfen**

Alle in diesem Umbau eingeführten Literale gegen `po/de.po` prüfen:

```bash
grep -rhoE '_\("([^"]+)"\)' src/ | sed -E 's/_\("(.*)"\)/\1/' | sort -u > /tmp/strings.txt
while read -r s; do grep -q "msgid \"$s\"" po/de.po || echo "FEHLT: $s"; done < /tmp/strings.txt
```

Jede Meldung nachtragen. Entfallene `msgid`s (aus `DiagnosticsTable`, `HistorySelection`) dürfen stehenbleiben — sie stören nicht.

- [ ] **Schritt 3: README nachziehen**

Im Abschnitt, der das Manipulator-Panel und den Fork beschreibt, die neue Seitenstruktur in zwei bis drei Sätzen ergänzen: Kopfband mit Kennzahlen, Zeitachse, zweispaltige Arbeitsfläche, Detail-Panel, Suche und Filter, Capture im ⋯-Menü. Bau- und Ausrollanweisungen bleiben unverändert.

- [ ] **Schritt 4: Gesamtprüfung**

```bash
make check-unit && npx tsc --noEmit && make codecheck && make
```

- [ ] **Schritt 5: Sichtprüfung auf dem Roboter**

```bash
rsync -a dist/ robot@<robot>:~/cockpit-ros2-diagnostics/dist/
```

Durchgehen und je Punkt bestätigen:

1. Heller **und** dunkler Modus (Cockpit-Umschalter oben rechts) — keine unlesbaren Flächen, keine eigenen Farben.
2. Fensterbreite 1600 px und 900 px — Spalten stapeln, kein horizontaler Scrollbalken.
3. Gesunder Roboter — Seite fast einfarbig, Zustandssatz „betriebsbereit“, Auffälligkeiten eine Zeile.
4. Arm stromlos — Manipulator-Karte grau, Werte gedimmt, Erklärzeile sichtbar, keine Warnfarbe.
5. Joystick abgezogen — im Baum das Ein/Aus-Symbol, im Detail-Panel „gemeldet: Fehler“ samt Grund.
6. Zeitachse anklicken — friert ein, Kopfband-Zeitstempel springt auf den Schnappschuss, „Weiter“ läuft wieder an.
7. Suche und beide Filterstufen, danach „Filter zurücksetzen“.
8. Capture aus dem ⋯-Menü — Archiv entsteht, Download-Link erscheint unter dem Kopfband.

- [ ] **Schritt 6: Übergabe**

Dem Benutzer den Stand melden: was umgesetzt ist, welche Prüfungen liefen und welche Sichtprüfungen bestätigt sind. **Nicht committen, nicht pushen** — das macht der Benutzer selbst.
