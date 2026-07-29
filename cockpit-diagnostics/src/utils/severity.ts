/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- severity overrides + inactive level.
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

/*
 * Severity levels, and how this app deviates from the `diagnostic_msgs` scale.
 *
 * `diagnostic_msgs/DiagnosticStatus` only knows OK/WARN/ERROR/STALE. Two things
 * are missing for an operator view:
 *
 *  - "out of service": a subsystem that is deliberately switched off is neither
 *    OK (it is not working) nor a fault (nobody needs to do anything). Painting
 *    a powered-down arm yellow or red trains people to ignore colours.
 *  - some upstream nodes classify harmless conditions as ERROR, which drags the
 *    whole robot's rollup to red and hides real faults.
 *
 * INACTIVE is therefore a *display* level below OK. It is negative on purpose:
 * group levels roll up with Math.max(), so a group only reads "inactive" when
 * all of its children are, and a single real fault still wins.
 */
export const LEVEL_INACTIVE = -2;
export const LEVEL_NONE = -1; // no status of its own (tree scaffolding)
export const LEVEL_OK = 0;
export const LEVEL_WARN = 1;
export const LEVEL_ERROR = 2;
export const LEVEL_STALE = 3;

// Value key by which a publisher can ask for the inactive rendering itself.
// `manipulator_diagnostics` sets it while the arm is powered off: the status
// stays a standards-compliant OK for every other consumer (rqt_robot_monitor,
// the diagnostics capture), and only this UI paints it grey.
export const DISPLAY_KEY = "display";
export const DISPLAY_INACTIVE = "inactive";

export interface SeverityOverride {
    // Matched against the raw (aggregated) status name, as a suffix so the
    // analyzer path in front of it does not matter. Several names per rule,
    // because ros2_control reports the same condition under more than one
    // diagnostic task.
    nameEndsWith: string[];
    /*
     * Matched against *every* non-empty line of the reported message.
     *
     * Line-wise and exhaustive on purpose: ros2_control concatenates all the
     * problems it found into one message, separated by newlines. Matching a
     * substring would downgrade a status that reports the tolerated condition
     * *and* a real one ("High execution jitter …\nNot all controllers are
     * active"). Requiring every line to match means the moment anything else
     * shows up, the reported level stands.
     */
    messageLine: RegExp;
    level: number;
    // Shown in the detail drawer next to the reported level. Plain English
    // literal: it is translated at render time via cockpit.gettext, not here
    // (this table is evaluated before the translations are loaded).
    reason: string;
}

/*
 * Reclassification of upstream statuses.
 *
 * Deliberately narrow -- name *and* the complete message must match. Nothing is
 * hidden: the drawer shows the reported level alongside the displayed one,
 * together with the reason below.
 */
export const SEVERITY_OVERRIDES: SeverityOverride[] = [
    {
        // joy_node reports a permanent ERROR when no gamepad is plugged in.
        // On a robot that is normally driven from software, "no joystick" is
        // the standing configuration, not a fault -- and as an ERROR it makes
        // the whole platform rollup red forever, which buries real errors.
        nameEndsWith: ["joy_node: Joystick Driver Status"],
        messageLine: /^Joystick not open\.?$/,
        level: LEVEL_INACTIVE,
        reason: "No joystick connected - the driver is idle, not faulty.",
    },
    {
        /*
         * ros2_control raises ERROR as soon as an execution time deviates from
         * the nominal cycle -- and it does so under *two* diagnostic tasks, with
         * the identical message: once for the hardware components, once for the
         * controllers. The A200 base runs its control loop at 10 Hz over a
         * serial link, so occasional outliers (measured: 24 ms peak against a
         * 37 us average, on a 100 ms cycle) are inherent to the platform. The
         * controllers variant is intermittent, which is precisely why a
         * permanent red is unhelpful -- it says nothing about when it fires.
         *
         * Upstream-correct would be raising controller_manager's own
         * `diagnostics.threshold.{controllers,hardware_components}.*`; that
         * silences the message entirely instead of downgrading it, which is why
         * it is done here.
         */
        nameEndsWith: [
            "controller_manager: Controllers Activity",
            "controller_manager: Hardware Components Activity",
        ],
        messageLine: /^High execution jitter or mean error\b/,
        level: LEVEL_WARN,
        reason: "Cycle-time jitter on the 10 Hz base control loop - inherent to this platform, not a drive fault.",
    },
];

export interface OverrideResult {
    level: number;
    reason: string;
}

/*
 * Which level should this status be displayed at?
 *
 * Returns null when the reported level stands. Publisher intent (the
 * `display=inactive` value) wins over the table -- a node that describes
 * itself as out of service knows better than a rule written here.
 */
export const overrideFor = (
    rawName: string,
    message: string,
    values: { [key: string]: unknown } | null,
): OverrideResult | null => {
    if (values?.[DISPLAY_KEY] === DISPLAY_INACTIVE) {
        return { level: LEVEL_INACTIVE, reason: "Reported as out of service by the publisher." };
    }

    // ros2_control prefixes its messages with a newline, so drop empty lines
    // before deciding -- an all-whitespace message must not count as "every
    // line matched".
    const lines = message.split("\n").map(line => line.trim())
            .filter(line => line.length > 0);
    if (lines.length === 0) {
        return null;
    }

    for (const rule of SEVERITY_OVERRIDES) {
        const nameMatches = rule.nameEndsWith.some(suffix => rawName.endsWith(suffix));
        if (nameMatches && lines.every(line => rule.messageLine.test(line))) {
            return { level: rule.level, reason: rule.reason };
        }
    }
    return null;
};

/*
 * Roll overridden levels up into their analyzer groups.
 *
 * The aggregator publishes a status for every group as well, computed from the
 * *reported* child levels -- so without this, downgrading a leaf would leave
 * its group (and the top-level entry) red. Recomputation is limited to groups
 * that actually contain an override, so every untouched group keeps exactly the
 * level the aggregator published for it.
 *
 * Returns true when this subtree contains an override.
 */
export const rollUpOverrides = (entries: DiagnosticsEntry[]): boolean => {
    let touched = false;

    for (const entry of entries) {
        const childTouched = rollUpOverrides(entry.children);
        if (childTouched && entry.children.length > 0) {
            entry.severity_level = entry.children.reduce(
                (worst, child) => Math.max(worst, child.severity_level),
                LEVEL_INACTIVE
            );
        }
        touched = touched || childTouched || entry.override_reason !== null;
    }

    return touched;
};
