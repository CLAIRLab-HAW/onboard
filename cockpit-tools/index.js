// Cockpit-Anbindung: Docker-Aufrufe, Abfragetakt, Knoepfe, VNC-Adresse.
// Die einzige Entscheidungslogik liegt in status.js und wird dort geprueft.

import { classify, shouldPoll, resolveHost } from './status.js';

const CONTAINER = 'offboard-lite-moveit-rviz-1';
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

const state = { status: null, error: null, pending: null };
let pollTimer = null;
let everFetched = false;

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

    docker('inspect', '-f', '{{.State.Status}}', CONTAINER)
            .then(out => {
                state.status = out.trim();
                state.error = null;
            })
            .catch(ex => {
                state.status = null;
                state.error = (ex.message || String(ex)).trim();
            })
            .finally(() => {
                everFetched = true;
                render();
                schedulePoll();
            });
}

function run(action) {
    state.pending = action;
    render();

    docker(action, CONTAINER)
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
    el('container-name').textContent = CONTAINER;
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
