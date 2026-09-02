/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg.
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

import { DiagnosticsEntry } from "../interfaces";
import { LEVEL_ERROR, LEVEL_WARN } from "./severity";

/*
 * "warn" and "error" are thresholds, not exact levels -- hence the >= labels in
 * the UI. LEVEL_STALE is numerically 3 and therefore contained in both: a
 * status that stopped arriving is at least as interesting as the error it might
 * be hiding.
 */
export type FilterLevel = "all" | "warn" | "error";

export interface TreeFilterResult {
    // rawNames of every node that must be rendered.
    visible: Set<string>;
    // rawNames that must be expanded so a match deeper down is reachable. Only
    // ancestors -- a match itself keeps whatever expansion state the user set.
    expand: Set<string>;
    // How many nodes matched on their own; 0 drives the "nothing found" state.
    matches: number;
}

const thresholdFor = (level: FilterLevel): number | null => {
    if (level === "warn") return LEVEL_WARN;
    if (level === "error") return LEVEL_ERROR;
    return null;
};

const collect = (entries: DiagnosticsEntry[], into: Set<string>): void => {
    entries.forEach(entry => {
        into.add(entry.rawName);
        collect(entry.children, into);
    });
};

export const filterTree = (
    entries: DiagnosticsEntry[],
    query: string,
    level: FilterLevel,
): TreeFilterResult => {
    const needle = query.trim().toLowerCase();
    const threshold = thresholdFor(level);

    // Nothing to do: show the tree as the aggregator ordered it and leave the
    // user's own expansion state alone.
    if (needle === "" && threshold === null) {
        const visible = new Set<string>();
        collect(entries, visible);
        return { visible, expand: new Set<string>(), matches: visible.size };
    }

    const visible = new Set<string>();
    const expand = new Set<string>();
    let matches = 0;

    const matchesSelf = (entry: DiagnosticsEntry): boolean => {
        if (threshold !== null && entry.severity_level < threshold)
            return false;
        if (needle === "")
            return true;
        return entry.name.toLowerCase().includes(needle) ||
               entry.path.toLowerCase().includes(needle) ||
               entry.message.toLowerCase().includes(needle);
    };

    // Returns whether anything in this subtree is visible, so the caller can
    // decide whether to keep itself as the path to a hit.
    const walk = (entry: DiagnosticsEntry): boolean => {
        const childVisible = entry.children
                .map(walk)
                .some(Boolean);
        const self = matchesSelf(entry);

        if (self)
            matches += 1;

        if (self || childVisible) {
            visible.add(entry.rawName);
            if (childVisible)
                expand.add(entry.rawName);
            return true;
        }
        return false;
    };

    entries.forEach(walk);
    return { visible, expand, matches };
};
