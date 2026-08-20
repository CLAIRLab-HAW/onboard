// Prueft die reine Zustandsabbildung aus status.js -- ohne Browser, ohne
// Cockpit, ohne Docker:  node --test  (vom Paketverzeichnis aus).
import test from 'node:test';
import assert from 'node:assert/strict';

import { classify, shouldPoll, resolveHost, parseContainers, pickContainer, parseInspect, diagnoseVnc, hasCode } from '../status.js';

test('running ist gruen und laesst sich nur stoppen', () => {
    const s = classify({ status: 'running' });
    assert.equal(s.color, 'green');
    assert.equal(s.label, 'läuft');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, true);
});

test('exited ist grau -- gestoppt ist kein Fehler', () => {
    const s = classify({ status: 'exited' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'gestoppt');
    assert.equal(s.canStart, true);
    assert.equal(s.canStop, false);
});

test('created zaehlt wie gestoppt', () => {
    const s = classify({ status: 'created' });
    assert.equal(s.color, 'grey');
    assert.equal(s.canStart, true);
});

test('paused laesst sich stoppen, aber nicht starten', () => {
    const s = classify({ status: 'paused' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'pausiert');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, true);
});

test('restarting ist gelb und pulsiert', () => {
    const s = classify({ status: 'restarting' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.pulse, true);
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('dead ist rot und nicht startbar', () => {
    const s = classify({ status: 'dead' });
    assert.equal(s.color, 'red');
    assert.equal(s.canStart, false);
});

test('laufendes Start-Kommando schlaegt den gemeldeten Zustand', () => {
    const s = classify({ status: 'exited', pending: 'start' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.pulse, true);
    assert.equal(s.label, 'startet…');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('laufendes Stopp-Kommando ebenso', () => {
    const s = classify({ status: 'running', pending: 'stop' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.label, 'stoppt…');
    assert.equal(s.canStop, false);
});

test('fehlender Container ist grau mit Umrandung, nicht rot', () => {
    const s = classify({ error: 'Error: No such object: offboard-lite-moveit-rviz-1' });
    assert.equal(s.color, 'grey');
    assert.equal(s.outline, true);
    assert.equal(s.missing, true);
    assert.equal(s.label, 'nicht angelegt');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
    assert.match(s.detail, /docker compose .* up -d/);
});

test('auch die aeltere Docker-Wortwahl gilt als fehlender Container', () => {
    const s = classify({ error: 'Error response from daemon: No such container: x' });
    assert.equal(s.missing, true);
});

test('jeder andere Docker-Fehler ist rot und zeigt den Klartext', () => {
    const msg = 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock';
    const s = classify({ error: msg });
    assert.equal(s.color, 'red');
    assert.equal(s.missing, false);
    assert.equal(s.label, 'Docker nicht erreichbar');
    assert.equal(s.detail, msg);
});

test('vor der ersten Antwort wird nur geprueft', () => {
    const s = classify({});
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'wird geprüft…');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('unbekannter Status wird woertlich durchgereicht, statt geraten zu werden', () => {
    const s = classify({ status: 'removing' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'removing');
    assert.equal(s.canStart, false);
});

// --- Abfragetakt ---------------------------------------------------------

test('die erste Abfrage laeuft auch im Hintergrundtab', () => {
    // Sonst bleibt eine Seite, die nie im Vordergrund war, fuer immer auf
    // "wird geprueft..." stehen -- genau so am 2026-08-20 in der Vorschau
    // beobachtet, document.hidden war dort dauerhaft true.
    assert.equal(shouldPoll({ hidden: true, everFetched: false }), true);
});

test('spaetere Abfragen entfallen im Hintergrund', () => {
    assert.equal(shouldPoll({ hidden: true, everFetched: true }), false);
});

test('im Vordergrund wird immer abgefragt', () => {
    assert.equal(shouldPoll({ hidden: false, everFetched: true }), true);
    assert.equal(shouldPoll({ hidden: false, everFetched: false }), true);
});

// --- Adresse fuer den VNC-Viewer -----------------------------------------

const FALLBACK = '10.42.42.159';

test('normalerweise gilt die Adresse, unter der Cockpit aufgerufen wurde', () => {
    assert.equal(resolveHost({ locationHost: '10.42.42.159', fallback: FALLBACK }), '10.42.42.159');
    assert.equal(resolveHost({ locationHost: 'husky.vysion.cloud', fallback: FALLBACK }), 'husky.vysion.cloud');
});

test('ueber einen Cockpit-Sprungrechner zaehlt der Zielrechner, nicht die Adresszeile', () => {
    assert.equal(resolveHost({ transportHost: 'robot@10.42.42.159', locationHost: 'laptop.local', fallback: FALLBACK }),
                 '10.42.42.159');
});

test('localhost taugt nicht als VNC-Ziel und faellt auf die Roboteradresse zurueck', () => {
    // Cockpit direkt auf dem Roboter aufgerufen oder durch einen SSH-Tunnel:
    // "vnc://localhost:5900" zeigt dann auf den falschen Rechner.
    for (const h of ['localhost', '127.0.0.1', '::1', ''])
        assert.equal(resolveHost({ locationHost: h, fallback: FALLBACK }), FALLBACK);
    assert.equal(resolveHost({ transportHost: 'localhost', locationHost: '127.0.0.1', fallback: FALLBACK }), FALLBACK);
});

// --- Container finden, statt seinen Namen zu raten ------------------------

// Zeilen wie sie `docker ps -a --format
// '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}'`
// liefert.
const PS = [
    'offboard-lite-moveit-rviz-1\thusky-offboard-lite:jazzy\texited\tmoveit-rviz',
    'husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard',
].join('\n');

test('die Ausgabe von docker ps wird in Felder zerlegt', () => {
    const rows = parseContainers(PS);
    assert.equal(rows.length, 2);
    assert.deepEqual(rows[0], {
        name: 'offboard-lite-moveit-rviz-1',
        image: 'husky-offboard-lite:jazzy',
        state: 'exited',
        service: 'moveit-rviz',
    });
});

test('Leerzeilen und Schrott fliegen raus', () => {
    assert.deepEqual(parseContainers('\n\n   \n'), []);
    assert.deepEqual(parseContainers(''), []);
});

test('der Container wird am compose-Dienst erkannt, nicht am Verzeichnisnamen', () => {
    // Genau der Fall vom 2026-08-20: das Projekt liegt woanders, also heisst
    // der Container anders -- die Seite muss ihn trotzdem finden.
    const rows = parseContainers('husky-offboard-lite-moveit-rviz-1\tirgendwas:neu\trunning\tmoveit-rviz');
    const hit = pickContainer(rows);
    assert.equal(hit.container.name, 'husky-offboard-lite-moveit-rviz-1');
    assert.equal(hit.container.state, 'running');
});

test('ohne compose-Label reicht das Image als Kennzeichen', () => {
    const rows = parseContainers('lite\tghcr.io/clairlab-haw/husky-offboard-lite:jazzy\texited\t');
    assert.equal(pickContainer(rows).container.name, 'lite');
});

test('der grosse husky-offboard-Container wird nicht mitgenommen', () => {
    const rows = parseContainers('husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard');
    assert.equal(pickContainer(rows).container, null);
});

test('aus mehreren Treffern gewinnt der laufende', () => {
    const rows = parseContainers([
        'alt-moveit-rviz-1\thusky-offboard-lite:jazzy\texited\tmoveit-rviz',
        'neu-moveit-rviz-1\thusky-offboard-lite:jazzy\trunning\tmoveit-rviz',
    ].join('\n'));
    const hit = pickContainer(rows);
    assert.equal(hit.container.name, 'neu-moveit-rviz-1');
    assert.equal(hit.others.length, 1);
});

test('kein Treffer heisst kein Treffer', () => {
    const hit = pickContainer(parseContainers(PS.split('\n')[1]));
    assert.equal(hit.container, null);
    assert.deepEqual(hit.others, []);
});

test('kein Treffer in der Containerliste ist derselbe Zustand wie ein "No such object"', () => {
    const gefunden = classify({ missing: true });
    assert.equal(gefunden.missing, true);
    assert.equal(gefunden.label, 'nicht angelegt');
    assert.equal(gefunden.outline, true);
    assert.equal(gefunden.canStart, false);
});

test('der Hinweis bei "nicht angelegt" raet kein Verzeichnis', () => {
    // Der urspruengliche Text nannte hart "cd ~/offboard-lite" -- ein Pfad,
    // den die Seite gar nicht geprueft hat und der anderswo falsch ist.
    const s = classify({ missing: true });
    assert.doesNotMatch(s.detail, /cd\s+~/);
    assert.match(s.detail, /docker compose .* up -d/);
});

// --- Warum der VNC-Port von aussen zu ist --------------------------------
//
// Am 2026-08-20 am Roboter gemessen: 6080 offen, 5900 keine Antwort. Zwei
// Ursachen erzeugen genau das, beide entstehen beim ANLEGEN des Containers
// und ueberleben jedes `docker start`.

const INSPECT_GUT = 'host\nROS_DOMAIN_ID=0\nVNC_PASSWORD=husky\nRVIZ_AUTOSTART=1\n';
const INSPECT_OHNE_PW = 'host\nROS_DOMAIN_ID=0\nRVIZ_AUTOSTART=1\n';
const INSPECT_BRIDGE = 'default\nVNC_PASSWORD=husky\n';

test('inspect-Ausgabe wird in Netzmodus und Umgebung zerlegt', () => {
    const i = parseInspect(INSPECT_GUT);
    assert.equal(i.networkMode, 'host');
    assert.ok(i.env.includes('VNC_PASSWORD=husky'));
});

test('mit Host-Netz und Passwort ist nichts zu melden', () => {
    assert.deepEqual(diagnoseVnc(parseInspect(INSPECT_GUT)), []);
});

test('ohne VNC_PASSWORD lauscht x11vnc nur auf localhost', () => {
    const [note] = diagnoseVnc(parseInspect(INSPECT_OHNE_PW));
    assert.equal(note.code, 'no-password');
    assert.match(note.text, /VNC_PASSWORD/);
    assert.match(note.text, /neu anlegen/i);
});

test('ein leeres VNC_PASSWORD zaehlt wie gar keines', () => {
    assert.equal(diagnoseVnc(parseInspect('host\nVNC_PASSWORD=\n')).length, 1);
});

test('ohne Host-Netz liegt 5900 nur auf dem Loopback des Roboters', () => {
    const notes = diagnoseVnc(parseInspect(INSPECT_BRIDGE));
    assert.equal(notes.length, 1);
    assert.equal(notes[0].code, 'bridge-network');
    assert.match(notes[0].text, /docker-compose\.robot\.yml/);
});

test('beide Ursachen zugleich werden auch beide genannt', () => {
    const codes = diagnoseVnc(parseInspect('default\nROS_DOMAIN_ID=0\n')).map(n => n.code);
    assert.deepEqual(codes, ['no-password', 'bridge-network']);
});

test('der Passwort-Hinweis widerspricht der Diagnose nicht', () => {
    // Solange die Seite meldet, dass gar kein Passwort gesetzt ist, darf sie
    // daneben nicht behaupten, der Viewer frage nach einem.
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_OHNE_PW)), 'no-password'), true);
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_GUT)), 'no-password'), false);
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_BRIDGE)), 'no-password'), false);
});

test('ohne inspect-Daten wird nichts behauptet', () => {
    assert.deepEqual(diagnoseVnc(null), []);
    assert.deepEqual(diagnoseVnc(parseInspect('')), []);
});
