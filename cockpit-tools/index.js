// Cockpit-Anbindung: Docker-Aufrufe, Abfragetakt, Knoepfe, VNC-Adresse.
// Die einzige Entscheidungslogik liegt in status.js und wird dort geprueft.

import {
    classify, shouldPoll, resolveHost,
    parseContainers, pickContainer,
    parseInspect, diagnoseVnc, hasCode, settleProbe,
} from './status.js';

// Der Containername wird NICHT geraten: compose bildet ihn aus dem
// Verzeichnisnamen (<projekt>-moveit-rviz-1), er aendert sich also, sobald das
// Projekt umzieht. Die Seite sucht ihn stattdessen in `docker ps -a` heraus --
// am compose-Dienst und am Image (siehe pickContainer in status.js).
const PS_FORMAT = '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}';

// Netzmodus in der ersten Zeile, danach die Umgebung -- daraus beantwortet
// diagnoseVnc(), warum Port 5900 von aussen zu ist.
const INSPECT_FORMAT = '{{.HostConfig.NetworkMode}}{{"\n"}}{{range .Config.Env}}{{println .}}{{end}}';

// Lauscht IM Container ueberhaupt jemand auf 5900? Das trennt einen toten
// Desktop von einem, der nur nach aussen nicht erreichbar ist -- von aussen
// sehen beide gleich aus. bash kann das ohne jedes Zusatzwerkzeug (kein ss,
// kein netstat, kein pgrep noetig).
const PROBE_5900 = 'exec 3<>/dev/tcp/127.0.0.1/5900 2>/dev/null && echo up || echo down';
const VNC_PORT = 5900;

// Faellt ein, wenn die Adresszeile kein brauchbares VNC-Ziel hergibt -- also
// wenn Cockpit direkt auf dem Roboter oder durch einen SSH-Tunnel geoeffnet
// wurde und dort "localhost" steht. Anderes Netz (netbird), andere Adresse:
// hier eintragen.
const ROBOT_HOST = '10.42.42.159';
const POLL_IDLE_MS = 3000;

// Auf diesem Roboter ist Docker das SNAP-Docker: das Binary liegt in
// /snap/bin, und die Cockpit-Bridge garantiert keinen Login-PATH. Ohne das
// vorangestellte /snap/bin schlaegt jeder Aufruf mit "docker: not found" fehl
// -- was wie ein fehlender Docker aussieht und keiner ist.
const PATH_PREFIX = 'PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin:$PATH; exec docker "$@"';

const state = { status: null, error: null, pending: null, missing: false };
let pollTimer = null;
let everFetched = false;
let container = null;      // der gefundene Container, sobald es einen gibt
let vncNotes = [];         // warum 5900 von aussen zu ist (leer = alles gut)
let inspectedKey = null;   // fuer welchen Container+Zustand das schon geprueft ist
let probeState = null;     // geglaettete 5900-Messung (siehe settleProbe)

function docker(...args) {
    return cockpit.spawn(['/bin/sh', '-c', PATH_PREFIX, 'sh', ...args],
                         { superuser: 'require', err: 'message' });
}

function el(id) {
    return document.getElementById(id);
}

function render() {
    const s = classify(state);

    const ball = el('ball');
    ball.className = 'ball ball-' + s.color
                   + (s.pulse ? ' ball-pulse' : '')
                   + (s.outline ? ' ball-outline' : '');
    ball.setAttribute('aria-label', 'Status: ' + s.label);
    ball.title = s.label;

    el('status-label').textContent = s.label;

    const detail = el('status-detail');
    detail.textContent = s.detail;
    detail.hidden = !s.detail;
    detail.classList.toggle('detail-error', s.color === 'red');

    el('btn-start').disabled = !s.canStart;
    el('btn-stop').disabled = !s.canStop;

    // Welchen Container die Seite gerade bedient -- sonst raet der Leser bei
    // "nicht angelegt", wonach ueberhaupt gesucht wurde.
    el('container-name').textContent = container ? container.name : '—';

    const diag = el('vnc-diagnose');
    diag.textContent = vncNotes.map(n => n.text).join('\n\n');
    diag.hidden = vncNotes.length === 0;

    // Kein Widerspruch auf einer Seite: solange die Diagnose sagt, dass gar
    // kein Passwort gesetzt ist, verschwindet der Hinweis, der Viewer frage
    // nach einem.
    el('hint-password').hidden = hasCode(vncNotes, 'no-password');

    const extra = el('container-extra');
    if (container && container.others && container.others.length > 0) {
        extra.textContent = 'Weitere passende Container: '
                          + container.others.map(o => o.name).join(', ')
                          + ' — bedient wird der oben genannte.';
        extra.hidden = false;
    } else {
        extra.hidden = true;
    }
}

function schedulePoll(ms = POLL_IDLE_MS) {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(poll, ms);
}

function poll() {
    window.clearTimeout(pollTimer);

    if (!shouldPoll({ hidden: document.hidden, everFetched })) {
        schedulePoll();
        return;
    }

    docker('ps', '-a', '--format', PS_FORMAT)
            .then(out => {
                const hit = pickContainer(parseContainers(out));
                container = hit.container ? { ...hit.container, others: hit.others } : null;
                state.status = hit.container ? hit.container.state : null;
                state.missing = !hit.container;
                state.error = null;
            })
            .catch(ex => {
                container = null;
                state.status = null;
                state.missing = false;
                state.error = (ex.message || String(ex)).trim();
            })
            .finally(() => {
                everFetched = true;
                render();
                refreshDiagnosis();
                schedulePoll();
            });
}

// Ein zweiter Docker-Aufruf, aber nicht im 3-Sekunden-Takt: Netzmodus und
// Umgebung eines Containers aendern sich nur beim Neuanlegen, nicht im
// Betrieb. Neu geprueft wird deshalb erst, wenn ein anderer Container
// gefunden wurde oder er seinen Zustand gewechselt hat.
function refreshDiagnosis() {
    if (!container) {
        vncNotes = [];
        inspectedKey = null;
        probeState = null;
        return;
    }

    const key = container.name + '|' + container.state;
    const settled = probeState && probeState.value !== null;

    // Netzmodus und Umgebung aendern sich nur beim Neuanlegen -- die einmal
    // je Container zu pruefen genuegt. Die 5900-Messung dagegen laeuft weiter,
    // bis sie zu einem Ergebnis gekommen ist (der Desktop braucht nach dem
    // Start ein paar Sekunden, siehe settleProbe).
    if (key === inspectedKey && settled)
        return;
    inspectedKey = key;

    const info = docker('inspect', '-f', INSPECT_FORMAT, container.name)
            .then(parseInspect)
            .catch(() => null);

    const probe = container.state === 'running'
        ? docker('exec', container.name, 'bash', '-c', PROBE_5900)
                .then(out => out.trim())
                .catch(() => null)
        : Promise.resolve(null);

    Promise.all([info, probe])
            .then(([parsed, measured]) => {
                probeState = container.state === 'running'
                    ? settleProbe(probeState, measured)
                    : null;
                // Die Diagnose ist eine Zugabe -- ohne inspect-Daten behauptet
                // sie nichts, statt zu raten.
                vncNotes = diagnoseVnc(parsed, { probe: probeState ? probeState.value : null });
            })
            .finally(render);
}

function run(action) {
    if (!container)
        return;

    state.pending = action;
    render();

    docker(action, container.name)
            .then(() => {
                state.error = null;
            })
            .catch(ex => {
                state.error = (ex.message || String(ex)).trim();
            })
            .finally(() => {
                state.pending = null;
                poll();          // sofort nachsehen, statt den Takt abzuwarten
            });
}

function vncHost() {
    return resolveHost({
        transportHost: cockpit.transport.host,
        locationHost: window.location.hostname,
        fallback: ROBOT_HOST,
    });
}

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext)
        return navigator.clipboard.writeText(text);

    // Cockpit laeuft hier ueber http (AllowUnencrypted) -- dann gibt es
    // navigator.clipboard nicht, und es bleibt der alte Weg.
    return new Promise((resolve, reject) => {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.className = 'offscreen';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error('copy failed'));
    });
}

function initVnc() {
    const url = 'vnc://' + vncHost() + ':' + VNC_PORT;

    el('vnc-url-text').textContent = url;
    el('vnc-link').setAttribute('href', url);
    el('open-cmd').textContent = 'open ' + url;

    el('btn-copy').addEventListener('click', () => {
        copyText(url).then(() => {
            const note = el('copy-note');
            note.hidden = false;
            window.setTimeout(() => { note.hidden = true }, 1500);
        }).catch(() => {
            const note = el('copy-note');
            note.textContent = 'Kopieren nicht möglich — Adresse von Hand markieren';
            note.hidden = false;
        });
    });
}

function init() {
    el('btn-start').addEventListener('click', () => run('start'));
    el('btn-stop').addEventListener('click', () => run('stop'));
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden)
            poll();
    });

    initVnc();
    render();
    poll();
}

document.addEventListener('DOMContentLoaded', init);
