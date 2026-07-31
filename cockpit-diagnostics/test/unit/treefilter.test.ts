/*
 * Search and level filter over the diagnostics tree.
 *
 * The rule that makes this non-trivial: a node stays visible when *it* matches
 * or when any descendant matches, because otherwise a hit three levels down
 * would appear without the path that explains where it lives.
 */
import { DiagnosticsEntry } from "../../src/interfaces";
import { filterTree } from "../../src/utils/treeFilter";
import { LEVEL_ERROR, LEVEL_OK, LEVEL_STALE, LEVEL_WARN } from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

const node = (
    name: string,
    level: number,
    message: string,
    children: DiagnosticsEntry[] = [],
): DiagnosticsEntry => ({
    name,
    path: `root/${name}`,
    rawName: `root/${name}`,
    message,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values: null,
    children,
});

const camera = node("camera_0", LEVEL_OK, "streaming 30 fps");
const imu = node("imu_0", LEVEL_WARN, "gyro bias not converged");
const gps = node("gps_0", LEVEL_STALE, "no message since 14:29:51");
const sensors = node("Sensors", LEVEL_STALE, "1 of 3 flagged", [camera, imu, gps]);
const motor = node("motor", LEVEL_ERROR, "overcurrent");
const platform = node("Platform", LEVEL_ERROR, "Error", [motor]);
const tree = [sensors, platform];

/* ------------------------------------------------------------ no filtering */

const none = filterTree(tree, "", "all");
check(none.visible.size === 6, "with no query and no filter everything is visible");
check(none.expand.size === 0, "an unfiltered tree must not be force-expanded");

/* ------------------------------------------------------------------ search */

const search = filterTree(tree, "gyro", "all");
check(search.visible.has(imu.rawName), "the matching node is visible");
check(search.visible.has(sensors.rawName), "its ancestor stays visible so the path is readable");
check(!search.visible.has(camera.rawName), "a non-matching sibling is hidden");
check(!search.visible.has(platform.rawName), "an unrelated branch is hidden");
check(search.expand.has(sensors.rawName), "ancestors of a hit are expanded");
check(!search.expand.has(imu.rawName), "the hit itself is not expanded");
check(search.matches === 1, "one node matched");

check(filterTree(tree, "GYRO", "all").visible.has(imu.rawName), "search ignores case");
check(filterTree(tree, "root/gps_0", "all").visible.has(gps.rawName), "search covers the path");
check(filterTree(tree, "camera_0", "all").visible.has(camera.rawName), "search covers the name");
check(filterTree(tree, "overcurrent", "all").visible.has(motor.rawName), "search covers the message");
check(filterTree(tree, "nothing here", "all").matches === 0, "a miss reports zero matches");
check(filterTree(tree, "nothing here", "all").visible.size === 0, "a miss hides everything");

/* ------------------------------------------------------------------ levels */

const warn = filterTree(tree, "", "warn");
check(warn.visible.has(imu.rawName), "warn keeps warnings");
check(warn.visible.has(gps.rawName), "warn keeps stale -- LEVEL_STALE is above LEVEL_WARN");
check(warn.visible.has(motor.rawName), "warn keeps errors");
check(!warn.visible.has(camera.rawName), "warn drops OK");

const error = filterTree(tree, "", "error");
check(error.visible.has(motor.rawName), "error keeps errors");
check(error.visible.has(gps.rawName), "error keeps stale -- numerically 3 is above 2");
check(!error.visible.has(imu.rawName), "error drops warnings");

/* -------------------------------------------------------------- combined */

const both = filterTree(tree, "gps", "error");
check(both.visible.has(gps.rawName), "search and filter combine with AND");
check(!both.visible.has(motor.rawName), "the error that does not match the search is dropped");

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} tree-filter assertion(s) failed`);
}

console.log("treeFilter: OK (ancestors kept, case-insensitive, stale in both levels, AND)");
