/*
 * Contract between the publishing node and this panel.
 *
 * The panel reads values out of `diagnostic_msgs` key/value pairs by string.
 * Nothing ties the two sides together at compile time, so renaming a key on the
 * publisher makes the field render as "unknown" instead of failing -- that is
 * exactly how `tool_power_on` -> `tool_power_commanded` reached the robot, and
 * how the same rename left `display` showing up as a phantom controller chip.
 *
 * This test closes that gap against a capture of what the robot really
 * publishes (`agg-armed.json`, taken from `/a200_0553/diagnostics_agg`):
 *
 *  1. every key literal the panel passes to valueOf/boolOf/numberOf is scraped
 *     out of the source and must exist somewhere in the manipulator statuses,
 *  2. the keys per status are additionally pinned by hand, so a key that moves
 *     to a *different* status is caught too,
 *  3. no metadata key may render as a controller chip.
 *
 * Refresh the fixture with:
 *   ros2 topic echo --once /<ns>/diagnostics_agg   (or scripts/dumpjson.py)
 */
import fs from 'node:fs';
import path from 'node:path';

import live from "./agg-armed.json";
import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
import {
    boolOf, collectManipulator, controllerRows, gripperPercent, jointRows, numberOf, valueOf,
} from "../../src/utils/manipulatorUtils";
import { DiagnosticsEntry } from "../../src/interfaces";
import { DISPLAY_INACTIVE, DISPLAY_KEY } from "../../src/utils/severity";

const problems: string[] = [];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const manipulator = collectManipulator(buildDiagnosticsTree(live as any[]));
if (!manipulator) {
    throw new Error("no manipulator statuses in the capture -- fixture stale?");
}

const statuses: Record<string, DiagnosticsEntry | null> = {
    armMode: manipulator.armMode,
    armControl: manipulator.armControl,
    armJoints: manipulator.armJoints,
    armControllers: manipulator.armControllers,
    gripper: manipulator.gripper,
};

const hasKey = (entry: DiagnosticsEntry | null, key: string) => valueOf(entry, key) !== null;
const anyStatusHas = (key: string) => Object.values(statuses).some(entry => hasKey(entry, key));

/* ---------------------------------------------------------------- 1. scraped */

// Keys the publisher is allowed not to send: legacy fallbacks, and keys that
// only exist while the gripper signal is invalid.
const OPTIONAL = new Set<string>([]);

const SOURCES = [
    "src/components/ManipulatorPanel.tsx",
    "src/utils/manipulatorUtils.ts",
];
const ACCESSOR = /\b(?:valueOf|boolOf|numberOf)\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*"([^"]+)"\s*\)/g;

const scraped = new Set<string>();
for (const source of SOURCES) {
    const text = fs.readFileSync(path.resolve(source), "utf8");
    for (const match of text.matchAll(ACCESSOR)) {
        scraped.add(match[1]);
    }
}
if (scraped.size === 0) {
    problems.push("scraped no keys at all -- has the accessor signature changed?");
}
for (const key of scraped) {
    if (!OPTIONAL.has(key) && !anyStatusHas(key)) {
        problems.push(`panel reads "${key}", but no manipulator status publishes it`);
    }
}

/* ------------------------------------------------------------- 2. per status */

/*
 * The keys the panel is contracted to read, per status. Checked in BOTH
 * directions below -- published by the node, and still read by the panel.
 * The second direction is what catches a rename that only survives through a
 * legacy fallback (as `tool_power_commanded ?? tool_power_on` once did): the
 * fallback keeps the scrape happy, but the primary key would vanish from it.
 * There is no such fallback left -- the rg6_control retirement dropped
 * `tool_power_commanded` and `high_force_preset` for good, so OPTIONAL is
 * empty and every key here has to be live on both sides.
 */
const PINNED: Record<string, string[]> = {
    armMode: ["robot_mode", "safety_mode", "robot_ip"],
    armControl: ["external_control", "motion_interface", "joint_state_rate_hz"],
    armJoints: ["joints"],
    armControllers: [],
    gripper: ["width_mm", "stroke_mm", "width_percent", "grip_detected", "busy",
        "tool_output_voltage_v", "signal_valid", "safety_failed",
        "last_command", "force_raw_v"],
};

for (const [status, keys] of Object.entries(PINNED)) {
    if (!statuses[status]) {
        problems.push(`status missing entirely: ${status}`);
        continue;
    }
    for (const key of keys) {
        if (!hasKey(statuses[status], key)) {
            problems.push(`${status}: publisher does not provide "${key}"`);
        }
        if (!scraped.has(key)) {
            problems.push(`${status}: panel no longer reads "${key}" (renamed? fallback left behind?)`);
        }
    }
}

// Per-joint keys are derived from the `joints` list, so check them through the
// same accessor the table uses.
const joints = jointRows(manipulator.armJoints);
if (joints.length === 0) {
    problems.push("armJoints: no joint rows");
}
for (const joint of joints) {
    if (joint.deg === "-") problems.push(`armJoints: "${joint.name}_deg" missing`);
    if (joint.rad === "-") problems.push(`armJoints: "${joint.name}_rad" missing`);
    if (joint.velocity === "-") problems.push(`armJoints: "${joint.name}_vel_rad_s" missing`);
}

/* --------------------------------------------------------- 3. no stray chips */

/*
 * Every value of the Arm Controllers status that is not known metadata becomes
 * a controller chip. The fixture is a healthy capture and carries no metadata
 * beyond `required`/`active_optional`, so DISPLAY_KEY -- which the node only
 * adds while the arm is switched off -- is injected here rather than shipping a
 * second, mislabelled fixture.
 */
const FORBIDDEN_CHIPS = ["display", "required", "active_optional"];
const withInactiveMarker: DiagnosticsEntry = {
    ...(manipulator.armControllers as DiagnosticsEntry),
    values: { ...manipulator.armControllers?.values, [DISPLAY_KEY]: DISPLAY_INACTIVE },
};
for (const source of [manipulator.armControllers, withInactiveMarker]) {
    for (const controller of controllerRows(source)) {
        if (FORBIDDEN_CHIPS.includes(controller.name)) {
            problems.push(`armControllers: metadata key "${controller.name}" rendered as a controller`);
        }
    }
}

/* ------------------------------------- 4. a healthy gripper reads as healthy */

if (valueOf(manipulator.gripper, "signal_valid") === "true") {
    if (gripperPercent(manipulator.gripper) === null) {
        problems.push("gripper: no opening bar although the signal is valid");
    }
    for (const key of ["grip_detected", "busy", "safety_failed"]) {
        if (boolOf(manipulator.gripper, key) === null) {
            problems.push(`gripper: "${key}" reads unknown although the signal is valid`);
        }
    }
    // Not a bool since the URCap path: the panel shows the measured supply,
    // and a gripper that answers cannot be sitting at a dead connector.
    if (numberOf(manipulator.gripper, "tool_output_voltage_v") === null) {
        problems.push('gripper: "tool_output_voltage_v" reads unknown although the signal is valid');
    }
}

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} contract violation(s)`);
}

console.log(`contract publisher/panel: OK (${scraped.size} scraped keys, ` +
            `${Object.values(PINNED).flat().length} pinned, ${joints.length} joints, no stray chips)`);
