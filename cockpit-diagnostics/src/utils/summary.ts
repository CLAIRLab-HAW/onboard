/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- summary counters and headline.
 *
 * Cockpit ROS 2 Diagnostics is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version.
 *
 * Cockpit ROS 2 Diagnostics is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with Cockpit; If not, see <http://www.gnu.org/licenses/>.
 */

import cockpit from 'cockpit';

import { DiagnosticsEntry, DiagnosticsStatus } from "../interfaces";
import { LEVEL_ERROR, LEVEL_OK, LEVEL_STALE, LEVEL_WARN } from "./severity";

const _ = cockpit.gettext;

export interface DiagnosticsSummary {
    errors: number;
    warnings: number;
    stale: number;
    // Every leaf, including the ones that are OK or out of service.
    total: number;
    // Worst *displayed* level across all leaves; LEVEL_OK for an empty tree.
    worst: number;
}

/*
 * Only leaves carry a status of their own.
 *
 * The aggregator publishes one status per analyzer group as well, computed from
 * its children. Counting those too reports the same fault once as a leaf and
 * again for every group above it -- on the a200 capture that is 24 statuses for
 * 15 actual ones.
 */
export const leafEntries = (entries: DiagnosticsEntry[]): DiagnosticsEntry[] =>
    entries.flatMap(entry => (entry.children.length === 0 ? [entry] : leafEntries(entry.children)));

export const summarise = (entries: DiagnosticsEntry[]): DiagnosticsSummary => {
    const leaves = leafEntries(entries);
    const count = (level: number) => leaves.filter(leaf => leaf.severity_level === level).length;

    return {
        errors: count(LEVEL_ERROR),
        warnings: count(LEVEL_WARN),
        stale: count(LEVEL_STALE),
        total: leaves.length,
        worst: leaves.reduce((worst, leaf) => Math.max(worst, leaf.severity_level), LEVEL_OK),
    };
};

/*
 * The sentence in the status band.
 *
 * Deliberately not derived from `worst` alone: the operator wants the count of
 * the worst thing, not just its name.
 */
export const headline = (summary: DiagnosticsSummary): string => {
    if (summary.errors > 0)
        return cockpit.format(cockpit.ngettext("$0 error", "$0 errors", summary.errors), summary.errors);
    if (summary.warnings > 0)
        return cockpit.format(cockpit.ngettext("$0 warning", "$0 warnings", summary.warnings), summary.warnings);
    if (summary.stale > 0)
        return cockpit.format(
            cockpit.ngettext("$0 stale message", "$0 stale messages", summary.stale), summary.stale);
    return _("operational");
};

/*
 * How urgent a level is for whoever is standing in front of the robot.
 *
 * NOT the numeric order of the constants: LEVEL_STALE is 3 and would sort above
 * LEVEL_ERROR = 2. A message that stopped arriving must not push a fault that is
 * being reported right now further down the list. Kept as a table so the
 * reversal is visible instead of hiding in a comparator.
 */
const URGENCY: Record<number, number> = {
    [LEVEL_ERROR]: 0,
    [LEVEL_STALE]: 1,
    [LEVEL_WARN]: 2,
};

const urgencyOf = (level: number): number => URGENCY[level] ?? Number.MAX_SAFE_INTEGER;

// Leaves worth acting on, worst first, ties broken by path so the order is
// stable between snapshots.
export const issueEntries = (entries: DiagnosticsEntry[]): DiagnosticsEntry[] =>
    leafEntries(entries)
            .filter(entry => entry.severity_level >= LEVEL_WARN)
            .sort((a, b) =>
                urgencyOf(a.severity_level) - urgencyOf(b.severity_level) ||
                a.path.localeCompare(b.path));

/*
 * How fast the aggregator is publishing, measured over the whole retained
 * history rather than the last gap -- a single late message should not make the
 * band flicker.
 */
export const updateRateHz = (history: DiagnosticsStatus[]): number | null => {
    if (history.length < 2)
        return null;

    const span = history[history.length - 1].timestamp - history[0].timestamp;
    if (span <= 0)
        return null;

    return ((history.length - 1) * 1000) / span;
};
