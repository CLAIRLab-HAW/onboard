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

if (problems.length > 0) {
    console.error(problems.map(p => "  FAIL " + p).join("\n"));
    throw new Error(`${problems.length} component assertion(s) failed`);
}

console.log("components: OK (5 labels, 5 distinct shapes, OK-is-silent rule)");
