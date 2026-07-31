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
check(gripperReadings.includes("pf-v6-c-progress"),
      "the gripper's opening bar sits inside the out-of-service wrapper");
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

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} component assertion(s) failed`);
}

console.log("components: OK (5 labels, 5 distinct shapes, OK-is-silent rule, timeline blanks-left + " +
            "no colour on healthy, detail panel empty/override-reason, tree level column + search filter, " +
            "connecting state moved to app level, manipulator out-of-service dimming reaches its selectors + " +
            "stripe variants + no stray Label)");
