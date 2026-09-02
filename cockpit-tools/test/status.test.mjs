// Checks the pure state mapping from status.js -- without a browser, without
// Cockpit, without Docker:  node --test  (from the package directory).
import test from 'node:test';
import assert from 'node:assert/strict';

import { classify, shouldPoll, resolveHost, parseContainers, pickContainer, parseInspect, diagnoseVnc, hasCode, settleProbe } from '../status.js';

test('running is green and can only be stopped', () => {
    const s = classify({ status: 'running' });
    assert.equal(s.color, 'green');
    assert.equal(s.label, 'running');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, true);
});

test('exited is grey -- stopped is not a fault', () => {
    const s = classify({ status: 'exited' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'stopped');
    assert.equal(s.canStart, true);
    assert.equal(s.canStop, false);
});

test('created counts as stopped', () => {
    const s = classify({ status: 'created' });
    assert.equal(s.color, 'grey');
    assert.equal(s.canStart, true);
});

test('paused can be stopped but not started', () => {
    const s = classify({ status: 'paused' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'paused');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, true);
});

test('restarting is yellow and pulses', () => {
    const s = classify({ status: 'restarting' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.pulse, true);
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('dead is red and cannot be started', () => {
    const s = classify({ status: 'dead' });
    assert.equal(s.color, 'red');
    assert.equal(s.canStart, false);
});

test('a start command in flight beats the reported state', () => {
    const s = classify({ status: 'exited', pending: 'start' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.pulse, true);
    assert.equal(s.label, 'starting…');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('a stop command in flight likewise', () => {
    const s = classify({ status: 'running', pending: 'stop' });
    assert.equal(s.color, 'yellow');
    assert.equal(s.label, 'stopping…');
    assert.equal(s.canStop, false);
});

test('a missing container is grey with an outline, not red', () => {
    const s = classify({ error: 'Error: No such object: offboard-lite-moveit-rviz-1' });
    assert.equal(s.color, 'grey');
    assert.equal(s.outline, true);
    assert.equal(s.missing, true);
    assert.equal(s.label, 'not created');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
    assert.match(s.detail, /docker compose .* up -d/);
});

test("docker's older wording counts as a missing container too", () => {
    const s = classify({ error: 'Error response from daemon: No such container: x' });
    assert.equal(s.missing, true);
});

test('every other Docker error is red and shows the plain text', () => {
    const msg = 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock';
    const s = classify({ error: msg });
    assert.equal(s.color, 'red');
    assert.equal(s.missing, false);
    assert.equal(s.label, 'Docker unreachable');
    assert.equal(s.detail, msg);
});

test('before the first answer it only checks', () => {
    const s = classify({});
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'checking…');
    assert.equal(s.canStart, false);
    assert.equal(s.canStop, false);
});

test('an unknown status is passed through verbatim instead of guessed', () => {
    const s = classify({ status: 'removing' });
    assert.equal(s.color, 'grey');
    assert.equal(s.label, 'removing');
    assert.equal(s.canStart, false);
});

// --- poll cadence ---------------------------------------------------------

test('the first poll runs in a background tab as well', () => {
    // Otherwise a page that was never in the foreground stands on "checking…"
    // forever -- observed exactly that way in the preview on 2026-08-20, where
    // document.hidden was permanently true.
    assert.equal(shouldPoll({ hidden: true, everFetched: false }), true);
});

test('later polls fall away in the background', () => {
    assert.equal(shouldPoll({ hidden: true, everFetched: true }), false);
});

test('in the foreground it always polls', () => {
    assert.equal(shouldPoll({ hidden: false, everFetched: true }), true);
    assert.equal(shouldPoll({ hidden: false, everFetched: false }), true);
});

// --- the address for the VNC viewer ---------------------------------------

const FALLBACK = '10.42.42.159';

test('normally the address Cockpit was opened under applies', () => {
    assert.equal(resolveHost({ locationHost: '10.42.42.159', fallback: FALLBACK }), '10.42.42.159');
    assert.equal(resolveHost({ locationHost: 'husky.vysion.cloud', fallback: FALLBACK }), 'husky.vysion.cloud');
});

test('over a Cockpit jump host the target machine counts, not the address bar', () => {
    assert.equal(resolveHost({ transportHost: 'robot@10.42.42.159', locationHost: 'laptop.local', fallback: FALLBACK }),
                 '10.42.42.159');
});

test('localhost is no VNC target and falls back to the robot address', () => {
    // Cockpit opened directly on the robot or through an SSH tunnel:
    // "vnc://localhost:5900" then points at the wrong machine.
    for (const h of ['localhost', '127.0.0.1', '::1', ''])
        assert.equal(resolveHost({ locationHost: h, fallback: FALLBACK }), FALLBACK);
    assert.equal(resolveHost({ transportHost: 'localhost', locationHost: '127.0.0.1', fallback: FALLBACK }), FALLBACK);
});

// --- find the container instead of guessing its name ----------------------

// Lines the way `docker ps -a --format
// '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}'`
// delivers them.
const PS = [
    'offboard-lite-moveit-rviz-1\thusky-offboard-lite:jazzy\texited\tmoveit-rviz',
    'husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard',
].join('\n');

test('the output of docker ps is split into fields', () => {
    const rows = parseContainers(PS);
    assert.equal(rows.length, 2);
    assert.deepEqual(rows[0], {
        name: 'offboard-lite-moveit-rviz-1',
        image: 'husky-offboard-lite:jazzy',
        state: 'exited',
        service: 'moveit-rviz',
    });
});

test('blank lines and junk fly out', () => {
    assert.deepEqual(parseContainers('\n\n   \n'), []);
    assert.deepEqual(parseContainers(''), []);
});

test('the container is recognised by the compose service, not the directory name', () => {
    // Exactly the case of 2026-08-20: the project lies elsewhere, so the
    // container is named differently -- the page has to find it all the same.
    const rows = parseContainers('husky-offboard-lite-moveit-rviz-1\tanything:new\trunning\tmoveit-rviz');
    const hit = pickContainer(rows);
    assert.equal(hit.container.name, 'husky-offboard-lite-moveit-rviz-1');
    assert.equal(hit.container.state, 'running');
});

test('without a compose label the image suffices as the mark', () => {
    const rows = parseContainers('lite\tghcr.io/clairlab-haw/husky-offboard-lite:jazzy\texited\t');
    assert.equal(pickContainer(rows).container.name, 'lite');
});

test('the big husky-offboard container is not taken along', () => {
    const rows = parseContainers('husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard');
    assert.equal(pickContainer(rows).container, null);
});

test('among several hits the running one wins', () => {
    const rows = parseContainers([
        'old-moveit-rviz-1\thusky-offboard-lite:jazzy\texited\tmoveit-rviz',
        'new-moveit-rviz-1\thusky-offboard-lite:jazzy\trunning\tmoveit-rviz',
    ].join('\n'));
    const hit = pickContainer(rows);
    assert.equal(hit.container.name, 'new-moveit-rviz-1');
    assert.equal(hit.others.length, 1);
});

test('no hit means no hit', () => {
    const hit = pickContainer(parseContainers(PS.split('\n')[1]));
    assert.equal(hit.container, null);
    assert.deepEqual(hit.others, []);
});

test('no hit in the container list is the same state as a "No such object"', () => {
    const found = classify({ missing: true });
    assert.equal(found.missing, true);
    assert.equal(found.label, 'not created');
    assert.equal(found.outline, true);
    assert.equal(found.canStart, false);
});

test('the hint on "not created" guesses no directory', () => {
    // The original text hard-named "cd ~/offboard-lite" -- a path the page never
    // checked and that is wrong anywhere else.
    const s = classify({ missing: true });
    assert.doesNotMatch(s.detail, /cd\s+~/);
    assert.match(s.detail, /docker compose .* up -d/);
});

// --- why the VNC port is closed from outside ------------------------------
//
// Measured on the robot on 2026-08-20: 6080 open, 5900 no answer. Two causes
// produce exactly that, both arise when the container is CREATED and survive
// every `docker start`.

const INSPECT_GOOD = 'host\nROS_DOMAIN_ID=0\nVNC_PASSWORD=husky\nRVIZ_AUTOSTART=1\n';
const INSPECT_NO_PW = 'host\nROS_DOMAIN_ID=0\nRVIZ_AUTOSTART=1\n';
const INSPECT_BRIDGE = 'default\nVNC_PASSWORD=husky\n';

test('the inspect output is split into network mode and environment', () => {
    const i = parseInspect(INSPECT_GOOD);
    assert.equal(i.networkMode, 'host');
    assert.ok(i.env.includes('VNC_PASSWORD=husky'));
});

test('with the host network and a password there is nothing to report', () => {
    assert.deepEqual(diagnoseVnc(parseInspect(INSPECT_GOOD)), []);
});

test('without VNC_PASSWORD x11vnc listens on localhost only', () => {
    const [note] = diagnoseVnc(parseInspect(INSPECT_NO_PW));
    assert.equal(note.code, 'no-password');
    assert.match(note.text, /VNC_PASSWORD/);
    assert.match(note.text, /create the container again/i);
});

test('an empty VNC_PASSWORD counts as none at all', () => {
    assert.equal(diagnoseVnc(parseInspect('host\nVNC_PASSWORD=\n')).length, 1);
});

test("without the host network 5900 lies on the robot's loopback only", () => {
    const notes = diagnoseVnc(parseInspect(INSPECT_BRIDGE));
    assert.equal(notes.length, 1);
    assert.equal(notes[0].code, 'bridge-network');
    assert.match(notes[0].text, /docker-compose\.robot\.yml/);
});

test('both causes at once are both named', () => {
    const codes = diagnoseVnc(parseInspect('default\nROS_DOMAIN_ID=0\n')).map(n => n.code);
    assert.deepEqual(codes, ['no-password', 'bridge-network']);
});

test('the password hint does not contradict the diagnosis', () => {
    // As long as the page reports that no password is set at all, it must not
    // claim beside it that the viewer asks for one.
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_NO_PW)), 'no-password'), true);
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_GOOD)), 'no-password'), false);
    assert.equal(hasCode(diagnoseVnc(parseInspect(INSPECT_BRIDGE)), 'no-password'), false);
});

test('without inspect data nothing is claimed', () => {
    assert.deepEqual(diagnoseVnc(null), []);
    assert.deepEqual(diagnoseVnc(parseInspect('')), []);
});

// --- the desktop inside the container is dead -----------------------------
//
// On a200-0553 on 2026-08-20: the container runs, but nobody listens on 5900.
// The cause was an orphaned Xvfb lock that survived `docker start`. Not
// distinguishable from a network problem from outside -- from inside it is.

test('when nobody listens on 5900 in the container, the page says so', () => {
    const notes = diagnoseVnc(parseInspect(INSPECT_GOOD), { probe: 'down' });
    assert.equal(notes.length, 1);
    assert.equal(notes[0].code, 'desktop-down');
    assert.match(notes[0].text, /force-recreate/);
});

test('when somebody listens there, there is nothing to report', () => {
    assert.deepEqual(diagnoseVnc(parseInspect(INSPECT_GOOD), { probe: 'up' }), []);
});

test('without a measurement nothing is claimed', () => {
    assert.deepEqual(diagnoseVnc(parseInspect(INSPECT_GOOD), { probe: null }), []);
    assert.deepEqual(diagnoseVnc(parseInspect(INSPECT_GOOD)), []);
});

test('the dead desktop stands before the reachability causes', () => {
    // Without a password x11vnc binds to 127.0.0.1 -- from INSIDE it answers all
    // the same. Both findings can therefore hold at once, and the more
    // fundamental one belongs on top.
    const codes = diagnoseVnc(parseInspect(INSPECT_NO_PW), { probe: 'down' }).map(n => n.code);
    assert.deepEqual(codes, ['desktop-down', 'no-password']);
});

test('a single "down" does not count yet -- the desktop needs seconds', () => {
    // Right after `docker start` the container stands on running while
    // Xvfb/fluxbox/x11vnc are still coming up. An immediate measurement would
    // report the start-up time as a defect.
    let st = settleProbe(null, 'down');
    assert.equal(st.value, null);
    st = settleProbe(st, 'down');
    assert.equal(st.value, null);
    st = settleProbe(st, 'down');
    assert.equal(st.value, 'down');
});

test('an "up" counts at once and clears the streak', () => {
    let st = settleProbe(null, 'down');
    st = settleProbe(st, 'up');
    assert.equal(st.value, 'up');
    assert.equal(st.streak, 0);
});

test('a failed measurement claims nothing and does not forget the streak', () => {
    let st = settleProbe(null, 'down');
    st = settleProbe(st, null);
    assert.equal(st.value, null);
    assert.equal(st.streak, 1);
});
