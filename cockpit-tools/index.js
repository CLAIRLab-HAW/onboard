// The Cockpit binding: Docker calls, poll cadence, buttons, VNC address.
// The only decision logic lives in status.js and is checked there.

import {
    classify, shouldPoll, resolveHost,
    parseContainers, pickContainer,
    parseInspect, diagnoseVnc, hasCode, settleProbe,
} from './status.js';

// The container name is NOT guessed: compose forms it from the directory name
// (<project>-moveit-rviz-1), so it changes as soon as the project moves. The
// page looks it up in `docker ps -a` instead -- by the compose service and by
// the image (see pickContainer in status.js).
const PS_FORMAT = '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}';

// The network mode on the first line, the environment after it -- from that
// diagnoseVnc() answers why port 5900 is closed from outside.
const INSPECT_FORMAT = '{{.HostConfig.NetworkMode}}{{"\n"}}{{range .Config.Env}}{{println .}}{{end}}';

// Is anybody listening on 5900 INSIDE the container at all? That separates a
// dead desktop from one that is merely unreachable from outside -- from outside
// the two look the same. bash can do it without any extra tool (no ss, no
// netstat, no pgrep needed).
const PROBE_5900 = 'exec 3<>/dev/tcp/127.0.0.1/5900 2>/dev/null && echo up || echo down';
const VNC_PORT = 5900;

// Steps in when the address bar yields no usable VNC target -- that is, when
// Cockpit was opened directly on the robot or through an SSH tunnel and reads
// "localhost" there. A different network (netbird) means a different address:
// enter it here.
const ROBOT_HOST = '10.42.42.159';
const POLL_IDLE_MS = 3000;

// On this robot Docker is the SNAP Docker: the binary lies in /snap/bin, and
// the Cockpit bridge guarantees no login PATH. Without the /snap/bin put in
// front, every call fails with "docker: not found" -- which looks like a
// missing Docker and is not one.
const PATH_PREFIX = 'PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin:$PATH; exec docker "$@"';

const state = { status: null, error: null, pending: null, missing: false };
let pollTimer = null;
let everFetched = false;
let container = null;      // the container found, as soon as there is one
let vncNotes = [];         // why 5900 is closed from outside (empty = all fine)
let inspectedKey = null;   // for which container+state that is already checked
let probeState = null;     // the smoothed 5900 measurement (see settleProbe)

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

    // Which container the page currently operates -- otherwise, on "not
    // created", the reader guesses what was even looked for.
    el('container-name').textContent = container ? container.name : '—';

    const diag = el('vnc-diagnose');
    diag.textContent = vncNotes.map(n => n.text).join('\n\n');
    diag.hidden = vncNotes.length === 0;

    // No contradiction on one page: as long as the diagnosis says no password
    // is set at all, the hint that the viewer asks for one disappears.
    el('hint-password').hidden = hasCode(vncNotes, 'no-password');

    const extra = el('container-extra');
    if (container && container.others && container.others.length > 0) {
        extra.textContent = 'Further matching containers: '
                          + container.others.map(o => o.name).join(', ')
                          + ' — the one named above is the one operated.';
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

// A second Docker call, but not on the 3-second cadence: the network mode and
// environment of a container change only when it is created anew, not while it
// runs. It is therefore re-checked only once a different container was found or
// this one changed its state.
function refreshDiagnosis() {
    if (!container) {
        vncNotes = [];
        inspectedKey = null;
        probeState = null;
        return;
    }

    const key = container.name + '|' + container.state;
    const settled = probeState && probeState.value !== null;

    // Network mode and environment change only when the container is created
    // anew -- checking those once per container is enough. The 5900 measurement,
    // by contrast, keeps running until it has come to a result (after a start the
    // desktop takes a few seconds, see settleProbe).
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
                // The diagnosis is an extra -- without inspect data it claims
                // nothing rather than guessing.
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
                poll();          // look at once instead of waiting for the cadence
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

    // Cockpit runs over http here (AllowUnencrypted) -- then there is no
    // navigator.clipboard, and the old way is what remains.
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
            note.textContent = 'Copying is not possible — select the address by hand';
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
