// Prueft die reine Zustandsabbildung aus status.js -- ohne Browser, ohne
// Cockpit, ohne Docker:  node --test  (vom Paketverzeichnis aus).
import test from 'node:test';
import assert from 'node:assert/strict';

import { classify, shouldPoll, resolveHost } from '../status.js';

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
