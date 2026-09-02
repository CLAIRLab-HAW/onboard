// The state mapping for the status ball.
//
// Deliberately a pure function without DOM, without cockpit.js and without
// Docker: it is the only place carrying decision logic and can therefore be
// checked here at the desk (test/status.test.mjs, `node --test test/`), while
// the rest of the page is nothing but buttons and text.
//
// The color agreement (deliberately not the usual traffic light):
//   green  = running
//   grey   = stopped -- that is the NORMAL CASE, not a fault
//   yellow = transition (a start/stop under way, restarting)
//   red    = fault: Docker does not answer, or the container is broken
// Were "stopped" red, the ball would glow alarmingly most of the time without
// anything being broken -- and a real fault would drown in it.

const MISSING_RE = /no such (object|container)/i;

/**
 * @param {object} state
 * @param {string} [state.status]  Docker state from `docker inspect -f '{{.State.Status}}'`
 * @param {string} [state.error]   error text of the last Docker call
 * @param {'start'|'stop'} [state.pending] the command in flight
 * @returns {{color:string,label:string,detail:string,pulse:boolean,
 *            outline:boolean,missing:boolean,canStart:boolean,canStop:boolean}}
 */
export function classify({status = null, error = null, pending = null, missing = false} = {}) {
    const base = {
        color: 'grey',
        label: '',
        detail: '',
        pulse: false,
        outline: false,
        missing: false,
        canStart: false,
        canStop: false,
    };

    // A command in flight beats everything else: while `docker start` works,
    // inspect keeps reporting the old state for minutes.
    if (pending === 'start')
        return {...base, color: 'yellow', pulse: true, label: 'starting…'};
    if (pending === 'stop')
        return {...base, color: 'yellow', pulse: true, label: 'stopping…'};

    if (missing || (error && MISSING_RE.test(error))) {
        return {
            ...base,
            outline: true,
            missing: true,
            label: 'not created',
            // No guessed path: the page does not know where the compose project
            // lives, and a wrong "cd" sends the reader into exactly the confusion
            // they are coming from.
            detail: 'There is no container from the image husky-offboard-lite on this '
                + 'machine (compose service moveit-rviz). Create it once, in the '
                + 'directory of the compose project: docker compose '
                + '-f docker-compose.yml -f docker-compose.robot.yml up -d',
        };
    }

    if (error)
        return {...base, color: 'red', label: 'Docker unreachable', detail: error};

    switch (status) {
        case null:
            return {...base, label: 'checking…'};
        case 'running':
            return {...base, color: 'green', label: 'running', canStop: true};
        case 'exited':
        case 'created':
            return {...base, label: 'stopped', canStart: true};
        case 'paused':
            // `docker start` fails on a paused container, `docker stop` does not --
            // hence only the stop button here.
            return {...base, label: 'paused', canStop: true};
        case 'restarting':
            return {...base, color: 'yellow', pulse: true, label: 'restarting…'};
        case 'dead':
            return {
                ...base,
                color: 'red',
                label: 'broken (dead)',
                detail: 'Docker cannot clean the container up any more. The only thing '
                    + 'left: docker rm -f and create it again.',
                canStop: true,
            };
        default:
            // Better to show the unknown state verbatim than to guess it.
            return {...base, label: status};
    }
}

/**
 * Whether to poll right now.
 *
 * In a background tab we economise -- the page stays loaded in Cockpit long
 * after one has moved elsewhere, and every poll is a Docker call with root
 * rights. The FIRST poll always runs, though: a page that was never in the
 * foreground (Cockpit opened in a background tab, or a browser reporting the
 * frame window as hidden) would otherwise stand on "checking…" forever.
 *
 * @param {{hidden:boolean, everFetched:boolean}} ctx
 * @returns {boolean}
 */
export function shouldPoll({hidden = false, everFetched = false} = {}) {
    return !hidden || !everFetched;
}

// Addresses that may well stand in the address bar but point at the wrong
// machine as a VNC target (Cockpit opened directly on the robot, or through an
// SSH tunnel).
const LOCAL_HOSTS = ['', 'localhost', '127.0.0.1', '::1'];

/**
 * The address under which the viewer reaches this machine's VNC port.
 *
 * @param {{transportHost?:string, locationHost?:string, fallback:string}} ctx
 *   transportHost = cockpit.transport.host (over a jump host the target
 *   machine, otherwise "localhost"), locationHost = window.location.hostname.
 * @returns {string}
 */
export function resolveHost({transportHost = null, locationHost = '', fallback = ''} = {}) {
    const via = (transportHost || '').replace(/^.*@/, '');
    if (via && !LOCAL_HOSTS.includes(via))
        return via;
    if (locationHost && !LOCAL_HOSTS.includes(locationHost))
        return locationHost;
    return fallback;
}

// --- Find the container instead of guessing its name ----------------------
//
// The name of a compose container is <project>-<service>-<n>, and by default
// the project is named after the DIRECTORY. A hard-wired
// "offboard-lite-moveit-rviz-1" is therefore a bet on where it lives -- lost on
// 2026-08-20, when the page reported "not created" on the robot and named a
// wrong directory alongside.
//
// It is recognised instead by two marks that know nothing of the location: the
// compose service (called moveit-rviz in this image's compose) and the image
// name.

const COMPOSE_SERVICE = 'moveit-rviz';
const IMAGE_HINT = 'offboard-lite';

/**
 * Splits the output of
 * `docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}'`.
 *
 * @param {string} text
 * @returns {Array<{name:string,image:string,state:string,service:string}>}
 */
export function parseContainers(text) {
    return (text || '')
        .split('\n')
        .map(line => line.trimEnd())
        .filter(line => line.trim() !== '')
        .map(line => {
            const [name = '', image = '', state = '', service = ''] = line.split('\t');
            return {
                name: name.trim(),
                image: image.trim(),
                state: state.trim(),
                service: service.trim(),
            };
        })
        .filter(row => row.name !== '');
}

/**
 * Picks the offboard-lite container out.
 *
 * @param {ReturnType<typeof parseContainers>} rows
 * @returns {{container: object|null, others: Array<object>}}
 *   `others` are further hits -- more than one is not a fault (an old container
 *   from a renamed project stays behind), but the page then says which one it
 *   operates.
 */
export function pickContainer(rows, {service = COMPOSE_SERVICE, imageHint = IMAGE_HINT} = {}) {
    const hits = (rows || []).filter(r =>
        r.service === service || r.image.includes(imageHint));

    if (hits.length === 0)
        return {container: null, others: []};

    // Running ones first: whoever has two containers means the one that works.
    const running = hits.filter(r => r.state === 'running');
    const chosen = running.length > 0 ? running[0] : hits[0];

    return {container: chosen, others: hits.filter(r => r !== chosen)};
}

// --- Why the VNC port is unreachable from outside -------------------------
//
// Measured on a200-0553 on 2026-08-20: 6080 open, 5900 no answer. Two causes
// produce that picture, and both arise when the container is CREATED -- a
// `docker start` cannot heal them, because it brings the container up with
// exactly its old configuration. The page therefore says which of the two
// applies instead of letting the reader guess.

/**
 * Splits the output of
 * `docker inspect -f '{{.HostConfig.NetworkMode}}{{"\n"}}{{range .Config.Env}}{{println .}}{{end}}'`.
 *
 * @param {string} text
 * @returns {{networkMode:string, env:string[]}|null}
 */
export function parseInspect(text) {
    const lines = (text || '').split('\n').map(l => l.trim()).filter(l => l !== '');
    if (lines.length === 0)
        return null;
    return {networkMode: lines[0], env: lines.slice(1)};
}

/**
 * @param {{networkMode:string, env:string[]}|null} info
 * @returns {Array<{code:string, text:string}>} empty when everything fits.
 *   The code exists to mute other places on the page: as long as "no-password"
 *   holds, nothing beside it may claim the viewer asks for one.
 */
export function diagnoseVnc(info, {probe = null} = {}) {
    if (!info)
        return [];

    const notes = [];

    // Measured from INSIDE: is anybody listening on 5900 at all? That separates
    // a dead desktop from one that is merely unreachable from outside -- from
    // outside the two look the same (6080 open, 5900 mute). When this note
    // stands, the two causes below are secondary.
    if (probe === 'down') {
        notes.push({
            code: 'desktop-down',
            text: 'Nobody is listening on port 5900 inside the container — the desktop did '
                + 'not come up on the restart. On images without the lock fix of 2026-08-20 '
                + 'this happens after every stop+start: Xvfb finds its old lock in /tmp and '
                + 'aborts, and x11vnc dies with it. The immediate remedy is '
                + 'docker compose ... up -d --force-recreate (a fresh /tmp); the lasting one '
                + 'is a rebuilt base image.',
        });
    }

    // Without a password x11vnc offers only security type "None" -- and then
    // binds to 127.0.0.1 instead of 0.0.0.0. noVNC on 6080 notices nothing of
    // it, because websockify connects inside the container. Hence exactly the
    // impression "but the container is running".
    const pw = info.env.find(e => e.startsWith('VNC_PASSWORD='));
    if (!pw || pw.slice('VNC_PASSWORD='.length).trim() === '') {
        notes.push({
            code: 'no-password',
            text: 'This container runs without VNC_PASSWORD — x11vnc then listens on '
                + 'localhost only, and a viewer from outside gets no connection (noVNC on '
                + '6080 still works). A restart does not change it: create the container '
                + 'again with VNC_PASSWORD set.',
        });
    }

    // Without the robot override the container runs in the bridge network, and
    // the port mapping binds 5900 to the robot's 127.0.0.1.
    if (info.networkMode && info.networkMode !== 'host') {
        notes.push({
            code: 'bridge-network',
            text: 'This container runs in the bridge network (' + info.networkMode + '), not '
                + "in the robot's network — port 5900 then lies on its 127.0.0.1 only. "
                + 'Create it again with -f docker-compose.robot.yml.',
        });
    }

    return notes;
}

/**
 * @param {Array<{code:string}>} notes
 * @param {string} code
 * @returns {boolean}
 */
export function hasCode(notes, code) {
    return (notes || []).some(n => n.code === code);
}

/**
 * Smooths the 5900 measurement: a single "down" is no finding.
 *
 * After `docker start` the container stands on `running` immediately, while
 * Xvfb, fluxbox and x11vnc are still coming up -- whoever measures then reports
 * the start-up time as a defect. "up", by contrast, counts at once: whoever
 * answers is alive.
 *
 * @param {{streak:number}|null} previous the previous stand
 * @param {'up'|'down'|null} probe the measurement ('null' = not measurable)
 * @param {{needed?:number}} [opts] how many "down" in a row are needed
 * @returns {{streak:number, value:'up'|'down'|null}}
 */
export function settleProbe(previous, probe, {needed = 3} = {}) {
    const streak = previous ? previous.streak : 0;

    if (probe === 'up')
        return {streak: 0, value: 'up'};

    // Not measurable (no bash in the container, exec refused): claim nothing,
    // but forget nothing either.
    if (probe !== 'down')
        return {streak, value: null};

    const next = streak + 1;
    return {streak: next, value: next >= needed ? 'down' : null};
}
