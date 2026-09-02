/*
 * Severity overrides and the inactive rollup.
 *
 * Messages here are verbatim captures from the a200-0553 (2026-07-29),
 * including ros2_control's leading newline -- that detail is why the matcher
 * works line-wise.
 *
 * The case this file exists for: ros2_control reports the *same* jitter message
 * under two diagnostic tasks, `Controllers Activity` and
 * `Hardware Components Activity`. The first release of the rule only listed the
 * hardware one, and since the controllers variant is intermittent it looked
 * fixed until it fired again.
 */
import fs from 'node:fs';
import path from 'node:path';

import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
import { DiagnosticsEntry } from "../../src/interfaces";
import {
    LEVEL_ERROR, LEVEL_INACTIVE, LEVEL_OK, LEVEL_WARN, overrideFor, SEVERITY_OVERRIDES,
} from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

const DRIVE = "/Clearpath Diagnostics/Platform/Drive System";
const JITTER_HW = "\nHigh execution jitter or mean error : [ a200_hardware a200_hardware ]";
const JITTER_CTRL = "\nHigh execution jitter or mean error : [ joint_state_broadcaster platform_velocity_controller ]";

const levelOf = (name: string, message: string) =>
    overrideFor(name, message, {})?.level ?? null;

/* ------------------------------------------------------- the jitter message */

check(levelOf(`${DRIVE}/controller_manager: Hardware Components Activity`, JITTER_HW) === LEVEL_WARN,
      "hardware-components jitter must be downgraded to WARNING");
check(levelOf(`${DRIVE}/controller_manager: Controllers Activity`, JITTER_CTRL) === LEVEL_WARN,
      "controllers jitter must be downgraded to WARNING");

/* --------------------------------------- a second problem keeps it an error */

// ros2_control concatenates everything it found into one message. As soon as
// anything other than the tolerated jitter appears, the reported level stands.
check(levelOf(`${DRIVE}/controller_manager: Controllers Activity`,
              JITTER_CTRL + "\nNot all controllers are active") === null,
      "an additional problem must NOT be downgraded");
check(levelOf(`${DRIVE}/controller_manager: Hardware Components Activity`,
              "\nSome hardware components are not active") === null,
      "a different hardware problem must NOT be downgraded");
check(levelOf(`${DRIVE}/controller_manager: Controller Manager Activity`, JITTER_CTRL) === null,
      "an unlisted status must NOT be downgraded, even with the same message");
check(levelOf(`${DRIVE}/controller_manager: Controllers Activity`, "\n   \n") === null,
      "a blank message must NOT count as 'every line matched'");

/* ------------------------------------------------------------ the joystick */

check(levelOf(`${DRIVE}/joy_node: Joystick Driver Status`, "Joystick not open.") === LEVEL_INACTIVE,
      "an unplugged joystick must read as out of service");
check(levelOf(`${DRIVE}/joy_node: Joystick Driver Status`, "Joystick error: read failed") === null,
      "a real joystick fault must stay an error");

/* ------------------------------------------------------------- the rollup */

const kv = (o: Record<string, string>) => Object.entries(o).map(([key, value]) => ({ key, value }));
const status = (name: string, level: number, message: string, values: Record<string, string> = {}) =>
    ({ name, message, level, hardware_id: "", values: kv(values) });

const find = (entries: DiagnosticsEntry[], name: string): DiagnosticsEntry | null => {
    for (const entry of entries) {
        if (entry.rawName === name) return entry;
        const found = find(entry.children, name);
        if (found) return found;
    }
    return null;
};

// Both leaves downgraded -> the group and everything above it must follow.
const downgraded = buildDiagnosticsTree([
    status(`${DRIVE}/controller_manager: Controllers Activity`, LEVEL_ERROR, JITTER_CTRL),
    status(`${DRIVE}/controller_manager: Hardware Components Activity`, LEVEL_ERROR, JITTER_HW),
    status(`${DRIVE}/joy_node: Joystick Driver Status`, LEVEL_ERROR, "Joystick not open."),
    status(DRIVE, LEVEL_ERROR, "Error"),
    status("/Clearpath Diagnostics/Platform", LEVEL_ERROR, "Error"),
    status("/Clearpath Diagnostics", LEVEL_ERROR, "Error"),
]);
check(find(downgraded, DRIVE)?.severity_level === LEVEL_WARN, "drive group must roll up to WARNING");
check(find(downgraded, "/Clearpath Diagnostics")?.severity_level === LEVEL_WARN,
      "top level must roll up to WARNING");
check(find(downgraded, `${DRIVE}/joy_node: Joystick Driver Status`)?.reported_level === LEVEL_ERROR,
      "the reported level must be preserved for the drawer");

// One genuine error in the same group -> everything above stays red.
const withRealError = buildDiagnosticsTree([
    status(`${DRIVE}/controller_manager: Controllers Activity`, LEVEL_ERROR,
           JITTER_CTRL + "\nNot all controllers are active"),
    status(`${DRIVE}/controller_manager: Hardware Components Activity`, LEVEL_ERROR, JITTER_HW),
    status(`${DRIVE}/joy_node: Joystick Driver Status`, LEVEL_ERROR, "Joystick not open."),
    status(DRIVE, LEVEL_ERROR, "Error"),
]);
check(find(withRealError, DRIVE)?.severity_level === LEVEL_ERROR,
      "a real error in the group must keep the group red");

// An untouched group keeps exactly what the aggregator published.
const untouched = buildDiagnosticsTree([
    status("/Clearpath Diagnostics/Sensors/Cameras/x: y", LEVEL_OK, "fine"),
    status("/Clearpath Diagnostics/Sensors/Cameras", LEVEL_WARN, "Warning"),
]);
check(find(untouched, "/Clearpath Diagnostics/Sensors/Cameras")?.severity_level === LEVEL_WARN,
      "an untouched group must not be recomputed");

/* ------------------------------------------------------- reasons are translated */

/*
 * The reason strings are passed to cockpit.gettext as *variables*, so a
 * changed literal does not break the build -- it just silently falls back to
 * English in a German UI. Pin them against the catalogue.
 */
const catalogue = fs.readFileSync(path.resolve("po/de.po"), "utf8");
const reasons = [
    ...SEVERITY_OVERRIDES.map(rule => rule.reason),
    // Not part of the table: the publisher-intent branch of overrideFor().
    "Reported as out of service by the publisher.",
];
for (const reason of reasons) {
    if (!catalogue.includes(`msgid "${reason}"`)) {
        problems.push(`po/de.po has no entry for the reason "${reason}"`);
    }
}

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} severity assertion(s) failed`);
}

console.log(`severity overrides: OK (both jitter tasks, extra-problem guard, joystick, rollup, ` +
            `${reasons.length} reasons translated)`);
