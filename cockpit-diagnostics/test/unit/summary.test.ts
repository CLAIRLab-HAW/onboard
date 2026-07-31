/*
 * Counting rules for the status band.
 *
 * Two traps this pins down:
 *
 *  1. Counting every node instead of the leaves reports the same fault once as
 *     a leaf and again in every analyzer group above it. `agg-armed.json` has
 *     24 aggregator statuses but only 15 leaves.
 *  2. `LEVEL_STALE` is numerically 3 and therefore *above* `LEVEL_ERROR` = 2.
 *     The old errors table filtered with `level >= 2` and silently swallowed
 *     stale statuses into the error count; stale now has a counter of its own,
 *     and it must not show up as an error.
 *
 * Counted is always the *displayed* level, never the reported one -- a
 * downgraded status must not drive the headline.
 */
import live from "./agg-armed.json";
import { buildDiagnosticsTree } from "../../src/components/RosConnectionManager";
import { DiagnosticsEntry, DiagnosticsStatus } from "../../src/interfaces";
import {
    headline, issueEntries, leafEntries, summarise, updateRateHz,
} from "../../src/utils/summary";
import {
    LEVEL_ERROR, LEVEL_INACTIVE, LEVEL_OK, LEVEL_STALE, LEVEL_WARN,
} from "../../src/utils/severity";

const problems: string[] = [];
const check = (condition: boolean, what: string) => {
    if (!condition) problems.push(what);
};

/* ------------------------------------------------- against the real capture */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const tree = buildDiagnosticsTree(live as any[]);
const real = summarise(tree);

check(leafEntries(tree).length === 15, "agg-armed.json has 15 leaves, not 24 statuses");
check(real.total === 15, "total counts leaves");
// The capture reports five ERRORs. Two of them are leaves and both are
// downgraded (jitter -> warning, joystick -> out of service); the other three
// are the analyzer groups above them.
check(real.errors === 0, "no leaf in the capture is displayed as an error");
check(real.warnings === 1, "the downgraded jitter status is the single warning");
check(real.stale === 0, "the capture has no stale status");
check(real.worst === LEVEL_WARN, "worst displayed level is the warning");
check(headline(real) === "1 warning", "headline names the warning count");

const issues = issueEntries(tree);
check(issues.length === 1, "only the warning is an issue -- out of service is not");
check(issues[0].name.trim() === "Hardware Components Activity", "the jitter status is the issue");

/* ------------------------------------------- synthetic tree for the corners */

const leaf = (name: string, level: number): DiagnosticsEntry => ({
    name,
    path: `group/${name}`,
    rawName: `group/${name}`,
    message: `${name} message`,
    severity_level: level,
    reported_level: level,
    override_reason: null,
    hardware_id: null,
    values: null,
    children: [],
});

const group = (name: string, children: DiagnosticsEntry[]): DiagnosticsEntry => ({
    ...leaf(name, Math.max(...children.map(c => c.severity_level))),
    children,
});

const mixed = [group("g", [
    leaf("boom", LEVEL_ERROR),
    leaf("old", LEVEL_STALE),
    leaf("hmm", LEVEL_WARN),
    leaf("fine", LEVEL_OK),
    leaf("off", LEVEL_INACTIVE),
])];
const s = summarise(mixed);

check(s.total === 5, "the group itself is not counted");
check(s.errors === 1, "stale must not be counted as an error");
check(s.stale === 1, "stale gets its own counter");
check(s.warnings === 1, "warnings are counted exactly");
check(headline(s) === "1 error", "an error outranks warning and stale in the headline");
check(headline(summarise([group("g", [leaf("old", LEVEL_STALE)])])) === "1 stale message",
      "stale reaches the headline when nothing worse is present");
check(headline(summarise([group("g", [leaf("fine", LEVEL_OK), leaf("off", LEVEL_INACTIVE)])])) === "operational",
      "OK and out of service together read as operational");
check(headline(summarise([])) === "operational", "an empty tree does not claim a fault");

/* ------------------------------------------------- urgency, not numeric order */

// LEVEL_STALE (3) sorts above LEVEL_ERROR (2) numerically. For an operator that
// is the wrong way round: a message that stopped arriving must not outrank a
// fault that is being reported right now.
const order = issueEntries(mixed).map(e => e.severity_level);
check(JSON.stringify(order) === JSON.stringify([LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN]),
      "issues sort error, stale, warning -- not by the numeric constants");

/* -------------------------------------------------------------------- rate */

const at = (ms: number): DiagnosticsStatus => ({ timestamp: ms, level: LEVEL_OK, diagnostics: [] });
check(updateRateHz([at(0), at(1000), at(2000), at(3000)]) === 1, "four samples one second apart are 1 Hz");
check(updateRateHz([at(0)]) === null, "a single sample has no rate");
check(updateRateHz([]) === null, "an empty history has no rate");
check(updateRateHz([at(100), at(100)]) === null, "identical timestamps have no rate");

/* ---------------------------------------------------- worst level edge cases */

// A fully powered-down robot is all LEVEL_INACTIVE leaves. Should not report OK.
check(summarise([group("g", [leaf("sleeping1", LEVEL_INACTIVE), leaf("sleeping2", LEVEL_INACTIVE)])]).worst === LEVEL_INACTIVE,
      "a tree whose leaves are all LEVEL_INACTIVE reports worst === LEVEL_INACTIVE");
// Empty tree has no leaves at all. Should be LEVEL_INACTIVE, not OK.
check(summarise([]).worst === LEVEL_INACTIVE,
      "an empty tree reports worst === LEVEL_INACTIVE");

/* ------------------------------------------------- tie-break by path */

// Two warnings at the same urgency should come back sorted by path.
const warnings = [group("g", [
    leaf("b_warning", LEVEL_WARN),
    leaf("a_warning", LEVEL_WARN),
])];
const warningIssues = issueEntries(warnings).map(e => e.path);
check(JSON.stringify(warningIssues) === JSON.stringify(["group/a_warning", "group/b_warning"]),
      "issues at the same urgency are sorted by path");

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} summary assertion(s) failed`);
}

console.log("summary: OK (leaf counting, stale vs error, headline, urgency order, rate)");
