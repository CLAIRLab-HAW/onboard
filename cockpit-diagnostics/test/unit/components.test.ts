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
import live from "./agg-armed.json";
import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
import { DiagnosticsEntry } from "../../src/interfaces";

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

/* -------------------------------------------------------------- StatusBand */

import { StatusBand } from "../../src/components/StatusBand";
import { headlineLevel, summarise } from "../../src/utils/summary";

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
check(healthy.includes("no data"), "an empty tree reads as no data, not falsely operational");
check(healthy.includes("/a200_0553"), "the namespace is shown");
check(!healthy.includes("Bridge disconnected"), "a connected bridge is not announced as disconnected");

check(band({ bridgeConnected: false }).includes("Bridge disconnected"),
      "a missing bridge is stated in the band, not only in the empty tree");

// With no namespace resolved yet (robot.yaml missing or not yet read) and no
// diagnostics, the heading must not render a dangling "— no data" with
// nothing in front of the separator, and its icon must stay silent -- LEVEL_NONE
// renders no "severity-icon" wrapper at all (see SeverityIcon), not the grey
// "out of service" glyph that `worst` alone would fall back to for an empty
// tree. (The band still has other, unrelated <svg> icons -- Pause and the ⋯
// menu toggle -- so those cannot be used to tell the headline icon apart.)
const noNamespace = band({ namespace: "" });
check(!noNamespace.includes(" — "), "with no namespace, the headline has no dangling separator");
check(noNamespace.includes("no data"), "and still states that there is no data");
check(!noNamespace.includes("severity-icon"), "and draws no headline icon at all for a fully empty state");

// Counts must come from the leaves of the real capture, not from the statuses.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const realTree = buildDiagnosticsTree(live as any[]);
const withData = band({ diagnostics: realTree });
// With counters to read it off, the sentence is redundant and gone: the band
// says "a200_0553" and the Warnings counter carries the number. What must NOT
// happen is losing it in the no-data case, where the counters all read zero --
// that is asserted above and is the reason the branch exists at all.
check(!withData.includes("1 warning"),
      "the sentence is dropped once a counter states the same thing");
check(!withData.includes(" — "),
      "and the separator goes with it, leaving the robot name alone");
check(withData.includes("Warnings"), "the counter is still there to carry it");
check(summarise(realTree).total === 15, "and counts 15 statuses");

// A counter at zero must not open a filter: "0 errors" is not something anybody
// wants to click through to a threshold that would still list stale messages.
// The Pause button and the ⋯ toggle are legitimate <button>s in the same band, so
// a bare "<button" substring would prove nothing -- only a KPI counter carries the
// "status-kpi" class on the button element itself.
const kpiIsButton = (html: string) => /<button[^>]*\bclass="[^"]*\bstatus-kpi\b[^"]*"[^>]*>/.test(html);

check(!kpiIsButton(healthy),
      "with every counter at zero, no counter renders as a clickable button");
check(kpiIsButton(withData),
      "the Warnings counter (1, from the real capture) renders as a clickable button");

/* --------------------------------------------------------------- Timeline */

import { Timeline } from "../../src/components/Timeline";
import { DiagnosticsStatus } from "../../src/interfaces";

const snapshotAt = (level: number): DiagnosticsStatus => ({ timestamp: Date.now(), level, diagnostics: [] });

const timelineMarkup = (diagHistory: DiagnosticsStatus[]) =>
    renderToStaticMarkup(React.createElement(Timeline, {
        diagHistory,
        setDiagStatusDisplay: () => undefined,
        isPaused: false,
        setIsPaused: () => undefined,
    }));

// HISTORY_SIZE is 30; two snapshots leave 28 unfilled slots, so both markers
// below are present and their order in the markup reflects render order.
const partial = timelineMarkup([snapshotAt(LEVEL_OK), snapshotAt(LEVEL_OK)]);
check(partial.indexOf("timeline-slot-empty") < partial.indexOf("timeline-slot-ok"),
      "unfilled slots render before real snapshots, keeping the newest one at the right edge");

check(!partial.includes("timeline-slot-warn") &&
      !partial.includes("timeline-slot-error") &&
      !partial.includes("timeline-slot-stale"),
      "an all-healthy history gets no status colour class");

// The hover has to carry the state sentence, not just the time: the three
// timestamp lines the previous component had were removed on the argument
// that this information now lives in the hover (plus the band's own
// timestamp), so the hover has to actually deliver it.
const warningSnapshot: DiagnosticsStatus = { timestamp: Date.now(), level: LEVEL_WARN, diagnostics: realTree };
check(timelineMarkup([warningSnapshot]).includes("1 warning"),
      "a timeline slot's hover states its own snapshot's warning count");

// The concrete regression: a snapshot with both an error and a stale leaf
// used to paint blue (stale sorts above error numerically), which is worse
// than the component this replaced -- that one at least painted red for
// anything at or above LEVEL_ERROR. `.level` here is computed exactly the way
// RosConnectionManager computes it in production.
const errorLeaf: DiagnosticsEntry = {
    name: "boom", path: "g/boom", rawName: "g/boom", message: "fault",
    severity_level: LEVEL_ERROR, reported_level: LEVEL_ERROR, override_reason: null,
    hardware_id: null, values: null, children: [],
};
const staleLeaf: DiagnosticsEntry = {
    name: "old", path: "g/old", rawName: "g/old", message: "quiet",
    severity_level: LEVEL_STALE, reported_level: LEVEL_STALE, override_reason: null,
    hardware_id: null, values: null, children: [],
};
const mixedTree = [errorLeaf, staleLeaf];
const mixedSnapshot: DiagnosticsStatus = {
    timestamp: Date.now(), level: headlineLevel(summarise(mixedTree)), diagnostics: mixedTree,
};
const mixedMarkup = timelineMarkup([mixedSnapshot]);
check(mixedMarkup.includes("timeline-slot-error"), "a snapshot with an error and a stale leaf paints as an error");
check(!mixedMarkup.includes("timeline-slot-stale"), "...and must not paint as stale");

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

/* --------------------------------------------------------------- DetailPanel */

import { DetailPanel, findEntryByRawName } from "../../src/components/DetailPanel";

const panelMarkup = (entry: DiagnosticsEntry | null) =>
    renderToStaticMarkup(React.createElement(DetailPanel, { entry, onClose: () => undefined }));

check(panelMarkup(null) === "", "with no status selected, the panel renders nothing");

// The joystick in the real capture is a genuinely downgraded status: ROS
// reports ERROR, this UI displays it as out of service (see utils/severity.ts).
// A reclassified status must never look like the original, so both the
// reported level and the reason it differs have to reach the markup.
const joystick = findEntryByRawName(
    realTree, "/Clearpath Diagnostics/Platform/Drive System/joy_node: Joystick Driver Status");
check(joystick !== null, "the real capture must contain the downgraded joystick status");

if (joystick) {
    const joystickMarkup = panelMarkup(joystick);
    check(joystickMarkup.includes(severityLabel(joystick.reported_level)),
          "a reclassified status states the level ROS actually reported");
    check(joystick.override_reason !== null && joystickMarkup.includes(joystick.override_reason),
          "and states why the displayed level differs from it");
}

/* ---------------------------------------------------------- DiagnosticsTreeTable */

import { DiagnosticsTreeTable } from "../../src/components/DiagnosticsTreeTable";

const treeNode = (name: string, level: number, message: string): DiagnosticsEntry => ({
    name,
    path: `root/${name}`,
    rawName: `root/${name}`,
    message,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values: null,
    children: [],
});

const okLeaf = treeNode("camera_0", LEVEL_OK, "streaming 30 fps");
const warnLeaf = treeNode("imu_0", LEVEL_WARN, "gyro bias not converged");

const treeMarkup = (over: Partial<React.ComponentProps<typeof DiagnosticsTreeTable>> = {}) =>
    renderToStaticMarkup(React.createElement(DiagnosticsTreeTable, {
        diagnostics: [okLeaf, warnLeaf],
        selectedRawName: null,
        setSelectedRawName: () => undefined,
        query: "",
        filterLevel: "all",
        onQueryChange: () => undefined,
        onFilterLevelChange: () => undefined,
        ...over,
    }));

// The level column is the only place severity shows now (Task 2 removed the
// icon that used to sit in front of the name), so an OK row must leave that
// cell empty while a row that is not OK must not -- otherwise the column
// would either shout at every healthy row or say nothing about a real one.
const levelCells = (html: string): string[] =>
    Array.from(html.matchAll(/<td[^>]*data-label="Level"[^>]*>([\s\S]*?)<\/td>/g), m => m[1]);

const bothRows = treeMarkup();
const cells = levelCells(bothRows);
check(cells.length === 2, "both rows render a level cell");
check(cells[0] === "", "an OK row's level cell is empty");
check(cells[1].includes("<svg"), "a warning row's level cell carries the severity icon");

// The tree must honour `visible` from filterTree, not just accept the props.
const filtered = treeMarkup({ query: "gyro" });
check(!filtered.includes(okLeaf.message), "a query hides a sibling that does not match");
check(filtered.includes(warnLeaf.message), "a query keeps the matching row");

// Task 11 moved the "Connecting" empty state up to app.tsx: the whole
// workspace is guarded there now, not just the tree, so the tree itself must
// no longer carry it (and no longer take a bridgeConnected prop to drive it).
const emptyTree = treeMarkup({ diagnostics: [] });
check(!emptyTree.includes("Connecting"), "the tree no longer renders its own connecting state");

/* --------------------------------------------------------- ManipulatorPanel */

// `realTree` only ever gives a healthy, powered arm -- the real capture has
// no way to show a powered-down arm or a gripper warning, so both states
// below are built by hand, the same way `treeNode` above stands in for a
// capture the fixture cannot provide.
import { ManipulatorPanel } from "../../src/components/ManipulatorPanel";

const manipEntry = (
    task: string,
    level: number,
    message: string,
    values: { [key: string]: unknown },
): DiagnosticsEntry => ({
    name: task,
    path: `root/manipulator_diagnostics: ${task}`,
    rawName: `root/manipulator_diagnostics: ${task}`,
    message,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values,
    children: [],
});

const manipMarkup = (diagnostics: DiagnosticsEntry[]) =>
    renderToStaticMarkup(React.createElement(ManipulatorPanel, {
        diagnostics,
        setSelectedRawName: () => undefined,
    }));

// ManipulatorPanel always renders the Arm card before the Gripper card
// (Grid: md=7 then md=5), and `state-card state-card-<variant>` is the
// literal class template Task 12 gives both cards -- splitting the markup on
// its second occurrence isolates one card's subtree from the other's.
const cardChunks = (html: string): [string, string] => {
    const first = html.indexOf("state-card state-card-");
    const second = html.indexOf("state-card state-card-", first + 1);
    return [html.slice(first, second), html.slice(second)];
};

/* -- out-of-service dimming: the class must reach the elements the SCSS rule targets -- */

const inactiveManipulator = [
    manipEntry("Arm Mode", LEVEL_INACTIVE, "Arm is switched off.",
               { robot_mode: "POWER_OFF", safety_mode: "NORMAL" }),
    manipEntry("Arm Control", LEVEL_INACTIVE, "Arm is switched off.",
               { external_control: "stopped", motion_interface: "dead" }),
    manipEntry("Arm Joints", LEVEL_INACTIVE, "Arm is switched off.",
               {
                   joints: "shoulder_pan_joint",
                   shoulder_pan_joint_deg: "12.0",
                   shoulder_pan_joint_rad: "0.209",
                   shoulder_pan_joint_vel_rad_s: "0.0",
               }),
    manipEntry("Arm Controllers", LEVEL_INACTIVE, "Arm is switched off.", {}),
    manipEntry("Gripper", LEVEL_INACTIVE, "Arm is switched off.",
               {
                   width_mm: "80",
                   stroke_mm: "160",
                   grip_detected: "false",
                   busy: "false",
                   tool_power_commanded: "false",
                   signal_valid: "false",
               }),
];

const inactiveHtml = manipMarkup(inactiveManipulator);
const [inactiveArmChunk, inactiveGripperChunk] = cardChunks(inactiveHtml);

check(inactiveArmChunk.includes("manipulator-out-of-service"),
      "an out-of-service arm renders the dimming class on the readings wrapper");
check(inactiveGripperChunk.includes("manipulator-out-of-service"),
      "an out-of-service gripper renders the dimming class on the readings wrapper");

// The SCSS rule dims by descendant selector (".manipulator-out-of-service
// .pf-v6-c-description-list" etc.), so the class existing somewhere in the
// card proves nothing on its own -- what has to hold is that the elements the
// selector actually targets sit after (i.e. inside) that wrapper, which is
// the wrapper's last-child position in the markup guarantees.
const afterMarker = (html: string) => html.slice(html.indexOf("manipulator-out-of-service"));
const armReadings = afterMarker(inactiveArmChunk);
const gripperReadings = afterMarker(inactiveGripperChunk);

check(armReadings.includes("pf-v6-c-description-list"),
      "the arm's description list sits inside the out-of-service wrapper, where the dimming selector reaches it");
check(armReadings.includes("pf-v6-c-table"),
      "the arm's joint table sits inside the out-of-service wrapper too -- a joint angle from a powered-down " +
      "arm must read as dimmed, not current");
// The drawing replaced the progress bar here. It has to stay inside the
// wrapper for the same reason the joint table does: a jaw position drawn at
// full confidence while nothing is being measured is the most convincing wrong
// thing this panel could show.
check(gripperReadings.includes("rg6-figure"),
      "the gripper drawing sits inside the out-of-service wrapper");
check(gripperReadings.includes("pf-v6-c-description-list"),
      "the gripper's description list sits inside the out-of-service wrapper");

// With no controllers published, the only remaining consumer of PatternFly's
// Label (the controller chips) has nothing to render -- so this fully
// out-of-service panel doubles as proof that Label did not creep back onto
// any of the rows Task 12 de-labelled (robot mode, safety mode, external
// control, motion link, grip detected, motion, tool power).
check(!inactiveHtml.includes("pf-v6-c-label"),
      "with no controller chips, the panel uses no PatternFly Label at all");

/* -- the stripe is the only state carrier left: wrong suffix = unstyled card -- */

const warnGripper = [
    manipEntry("Arm Mode", LEVEL_OK, "", { robot_mode: "RUNNING", safety_mode: "NORMAL" }),
    manipEntry("Arm Control", LEVEL_OK, "",
               { external_control: "running", motion_interface: "live", joint_state_rate_hz: "125" }),
    manipEntry("Arm Joints", LEVEL_OK, "", { joints: "" }),
    manipEntry("Arm Controllers", LEVEL_OK, "", {}),
    manipEntry("Gripper", LEVEL_WARN, "Tool voltage off.",
               { tool_power_commanded: "false", signal_valid: "false", grip_detected: "false", busy: "false" }),
];

const [okArmChunk, warnGripperChunk] = cardChunks(manipMarkup(warnGripper));

// `class="state-card state-card-<variant>"` is the entire attribute -- no
// other class follows the variant -- so the closing quote has to come right
// after it. Matching only the prefix would also accept a variant like
// "warning" for "warn": a real class-name drift that leaves the CSS selector
// (which matches whole class tokens, not prefixes) unable to find the card.
check(okArmChunk.startsWith('state-card state-card-quiet"'),
      "an OK arm card gets exactly the neutral (quiet, grey) stripe variant");
check(warnGripperChunk.startsWith('state-card state-card-warn"'),
      "a gripper reporting a warning gets exactly the warn stripe variant");
check(warnGripperChunk.includes("Tool voltage off."),
      "the warning message reaches the card as an alert, not just the stripe colour");

/* ------------------------------------------------------------- CaptureAlerts */

// useCapture itself talks to cockpit.spawn/cockpit.permission through a
// useEffect, neither of which exist in this stub, and renderToStaticMarkup
// never runs effects anyway -- so only CaptureAlerts, the pure display half,
// is honestly testable here. Its state is built by hand instead of by
// calling useCapture.
import { CaptureAlerts, CaptureState } from "../../src/components/DiagnosticsCapture";

const idleCapture: CaptureState = {
    isCapturing: false,
    errorMessage: null,
    downloadPath: null,
    adminAccess: true,
    capture: async () => undefined,
};

const alertsMarkup = (state: CaptureState) =>
    renderToStaticMarkup(React.createElement(CaptureAlerts, { state }));

check(alertsMarkup(idleCapture) === "", "with nothing captured yet, CaptureAlerts renders nothing");
check(alertsMarkup({ ...idleCapture, isCapturing: true }).includes("several minutes"),
      "a capture in progress shows the progress alert");
check(alertsMarkup({ ...idleCapture, errorMessage: "boom" }).includes("boom"),
      "a failed capture shows its error message");
check(alertsMarkup({ ...idleCapture, downloadPath: "/tmp/x.tar.gz" }).includes("Download Diagnostics File"),
      "a finished capture offers the download link");

/* -------------------------------------------------------------- Application */

// Application owns namespace/diagnostics state itself and populates it only
// through effects (websocket messages, file watches) that renderToStaticMarkup
// never runs -- so the one thing honestly reachable here, without those
// effects firing, is the very first render: no diagnostics yet. That must
// show the page-level connecting state added in Task 11, not the two-column
// workspace (which would need data neither this render pass nor the stub
// cockpit module can provide).
import { Application } from "../../src/app";
import { CookiesProvider } from "react-cookie";

const appMarkup = renderToStaticMarkup(
    React.createElement(CookiesProvider, null, React.createElement(Application)));
check(appMarkup.includes("Connecting"), "with no diagnostics yet, the page shows the connecting state");
check(!appMarkup.includes("All Diagnostics"), "and not the diagnostics tree");
check(!appMarkup.includes("workspace-secondary"), "nor the two-column workspace grid");

/* ------------------------------------------------------- GripperGraphic */

/*
 * The drawing replaced a labelled PatternFly Progress bar. Two things must
 * survive that swap or it is a regression dressed up as a feature: the value
 * has to reach a screen reader, and the picture has to be open exactly as far
 * as the measurement says -- not approximately, and not at a guessed pose when
 * nothing was measured at all.
 */
import { GripperGraphic } from "../../src/components/GripperGraphic";

const gripperMarkup = (
    percent: number | null,
    widthMm: string | null,
    strokeMm: string | null,
    gripDetected: boolean | null = false,
) => renderToStaticMarkup(React.createElement(GripperGraphic, {
    percent, widthMm, strokeMm, gripDetected,
}));

check(gripperMarkup(null, null, null) === "",
      "without a measurement the gripper draws nothing rather than a guessed pose");

const openMarkup = gripperMarkup(100, "160.0", "160");
const shutMarkup = gripperMarkup(0, "0.0", "160");

check(openMarkup.includes('aria-label="Opening: 160.0 of 160 mm"'),
      "the reading reaches a screen reader, as the replaced Progress bar did");
check(gripperMarkup(50, null, null).includes('aria-label="Opening: 50 %"'),
      "without width/stroke it falls back to the percentage, as the bar did");

// The jaws are the two <rect class="rg6-jaw">; their x is the jaw centre minus
// half the jaw thickness, so it grows with the opening.
const jawXs = (html: string) => [...html.matchAll(/class="rg6-jaw"[^>]*?x="(-?[\d.]+)"/g)]
        .map(m => Number(m[1]));
const jawXsAlt = (html: string) => [...html.matchAll(/x="(-?[\d.]+)"[^>]*?class="rg6-jaw"/g)]
        .map(m => Number(m[1]));
const jaws = (html: string) => { const a = jawXs(html); return a.length ? a : jawXsAlt(html); };

const openJaws = jaws(openMarkup);
const shutJaws = jaws(shutMarkup);
check(openJaws.length === 2 && shutJaws.length === 2, "two jaws are drawn");
// Fully open must put the jaws further apart than fully shut -- if the width
// were ignored, these two renders would be identical.
check(Math.max(...openJaws) > Math.max(...shutJaws),
      "the jaw gap follows the measured width");
check(openMarkup !== shutMarkup, "0 % and 100 % are not the same picture");

check(!gripperMarkup(60, "96.0", "160", false).includes('class="rg6-object"'),
      "no object is drawn when none is held");
check(gripperMarkup(60, "96.0", "160", true).includes('class="rg6-object"'),
      "a held object is drawn as a shape between the jaws");

// Severity colour must not leak into a measurement.
check(!/rg6-(jaw|link|object|body)[^>]*(danger|warning|success|status)/.test(openMarkup),
      "the drawing carries no status colour");


/* ------------------------------------------------------- GripperControl */

/*
 * The only control on this page that moves hardware. Its guards are tested as
 * a pure function because the component itself cannot be exercised here:
 * `renderToStaticMarkup` never runs effects, so the admin permission is never
 * read and the component always renders its fail-closed empty output. That
 * fail-closed default is asserted too -- it is the behaviour a broken or
 * missing permission lookup falls back to.
 */
import { GripperControl, gripperBlockedReason } from "../../src/components/GripperControl";

const guard = (over: Partial<Parameters<typeof gripperBlockedReason>[0]> = {}) =>
    gripperBlockedReason({
        connected: true, isInactive: false, percent: 80, busy: false,
        externalControlRunning: false, ...over,
    });

check(guard() === null, "a connected, idle, in-service gripper may be commanded");
check(guard({ connected: false }) === "Not connected to the robot.",
      "no connection blocks the command");
check(guard({ isInactive: true }) === "The end effector is out of service.",
      "an out-of-service end effector blocks the command");
check(guard({ percent: null }) === "No opening is being reported.",
      "no measurement blocks the command -- without tool voltage the RG6 reports nothing");
check(guard({ busy: true }) === "The gripper is still moving.",
      "a moving gripper blocks the command");
check(guard({ externalControlRunning: true }) === "The arm is under external control.",
      "external control blocks the command: every gripper command tears ExternalControl down");

// Unknown is not permission. `busy: null` means the driver did not say.
check(guard({ busy: null }) === null, "an unreported busy flag does not block by itself");

// The most fundamental obstacle wins, so the operator is told the actionable one.
check(guard({ connected: false, busy: true }) === "Not connected to the robot.",
      "the connection is reported before the movement");

check(renderToStaticMarkup(React.createElement(GripperControl, {
    ros: {}, namespace: "/a200_0553", percent: 80, busy: false,
    isInactive: false, externalControlRunning: false,
})) === "", "without a granted admin permission the control renders nothing at all");


/* --------------------------------------------- service schema resolution */

/*
 * The bug this pins down cost a live debugging round: calling a service failed
 * with "Cannot read properties of undefined (reading 'split')" deep inside the
 * message parser. Cause: the Foxglove protocol carries a service's schema two
 * ways -- the deprecated flat `requestSchema`/`responseSchema`, and the nested
 * `request`/`response` definitions that current bridges (foxglove_bridge 3.x on
 * this robot) actually send. The client read only the deprecated pair.
 */
import { serviceSchemaOf } from "../../src/components/../roslib/Impl";

const nested = {
    id: 1, name: "/rg6_control/close", type: "std_srvs/srv/Trigger",
    request: { encoding: "cdr", schemaName: "std_srvs/srv/Trigger_Request", schemaEncoding: "ros2msg", schema: "" },
    response: {
        encoding: "cdr", schemaName: "std_srvs/srv/Trigger_Response",
        schemaEncoding: "ros2msg", schema: "bool success\nstring message",
    },
};
const flat = {
    id: 2, name: "/rg6_control/open", type: "std_srvs/srv/Trigger",
    requestSchema: "", responseSchema: "bool success\nstring message",
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
check(serviceSchemaOf(nested as any, "response").schema === "bool success\nstring message",
      "the nested response definition is read -- this is the shape the robot's bridge sends");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
check(serviceSchemaOf(nested as any, "response").schemaEncoding === "ros2msg",
      "and its schemaEncoding travels with it, not from the channel branch");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
check(serviceSchemaOf(flat as any, "response").schema === "bool success\nstring message",
      "the deprecated flat form still works, so an older bridge keeps functioning");

// An empty request schema is legitimate: std_srvs/srv/Trigger takes no
// arguments, so both shapes carry "" and neither may be treated as missing.
// A truthiness check here would fall through to the deprecated field, find
// nothing, and throw on the one service this feature exists to call.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
check(serviceSchemaOf(nested as any, "request").schema === "",
      "an empty request schema is a value, not a missing field");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
check(serviceSchemaOf(flat as any, "request").schema === "",
      "same for the deprecated flat form");

let threw = false;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
try { serviceSchemaOf({ id: 3, name: "/x", type: "t" } as any, "request"); } catch { threw = true }
check(threw, "a service advertised with no schema at all fails loudly, naming the service");


if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} component assertion(s) failed`);
}

console.log("components: OK (5 labels, 5 distinct shapes, OK-is-silent rule, timeline blanks-left + " +
            "no colour on healthy, detail panel empty/override-reason, tree level column + search filter, " +
            "connecting state moved to app level, manipulator out-of-service dimming reaches its selectors + " +
            "stripe variants + no stray Label, gripper drawing scales with the measurement, gripper command guards, service schema resolution)");
