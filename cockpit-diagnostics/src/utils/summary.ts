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
import { LEVEL_ERROR, LEVEL_INACTIVE, LEVEL_NONE, LEVEL_STALE, LEVEL_WARN } from "./severity";

const _ = cockpit.gettext;

export interface DiagnosticsSummary {
    errors: number;
    warnings: number;
    stale: number;
    // Every leaf, including the ones that are OK or out of service.
    total: number;
    // Worst *displayed* level across all leaves; LEVEL_INACTIVE when there are no leaves.
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
        worst: leaves.reduce((worst, leaf) => Math.max(worst, leaf.severity_level), LEVEL_INACTIVE),
    };
};

/*
 * The sentence in the status band.
 *
 * Deliberately not derived from `worst` alone: the operator wants the count of
 * the worst thing, not just its name.
 */
export const headline = (summary: DiagnosticsSummary): string => {
    // No leaves at all -- e.g. the bridge is down, or robot.yaml has not
    // resolved a namespace yet. "operational" here would be exactly the false
    // reassurance this redesign set out to remove: there is no data, not a
    // clean bill of health.
    if (summary.total === 0)
        return _("no data");
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
 * Which single level best represents a summary -- for an icon, or a CSS
 * variant. Mirrors headline()'s own branch order (errors, then warnings, then
 * stale) so the symbol drawn next to the sentence never contradicts it.
 * `summary.worst` alone cannot do this: it is a Math.max() over the leaves,
 * and LEVEL_STALE (3) is numerically above LEVEL_ERROR (2), so a tree with
 * both an error and a stale leaf would report worst === LEVEL_STALE and the
 * icon would show a calm blue clock next to a sentence naming the error.
 *
 * LEVEL_NONE when there are no leaves at all, so the caller can render no
 * symbol (see SeverityIcon) instead of the grey "out of service" glyph that
 * `worst` would otherwise fall back to for an empty tree.
 */
export const headlineLevel = (summary: DiagnosticsSummary): number => {
    if (summary.total === 0)
        return LEVEL_NONE;
    if (summary.errors > 0)
        return LEVEL_ERROR;
    if (summary.warnings > 0)
        return LEVEL_WARN;
    if (summary.stale > 0)
        return LEVEL_STALE;
    return summary.worst;
};

export type StateVariant = "error" | "stale" | "warn" | "quiet";

/*
 * The CSS variant for a single, already-resolved level (an icon's level, or
 * a card's rolled-up severity) -- never a raw Math.max() over several
 * entries, which is exactly the mistake this replaces three near-identical
 * copies of (StatusBand, Timeline, ManipulatorPanel all had their own
 * `level >= LEVEL_STALE ? ...` chain). Exact equality, not thresholds: the
 * six severity levels do not form a "worse than" ladder, so a `>=` chain is
 * never the right tool here regardless of ordering.
 */
export const variantForLevel = (level: number): StateVariant =>
    level === LEVEL_ERROR
        ? "error"
        : level === LEVEL_STALE
            ? "stale"
            : level === LEVEL_WARN
                ? "warn"
                : "quiet";

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
