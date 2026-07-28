/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- manipulator extension.
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
 * Manipulator (arm + end effector) view over the aggregated diagnostics.
 *
 * The data comes from the `manipulator_diagnostics` node, which translates the
 * UR driver's `ur_dashboard_msgs` and the `rg6_msgs/GripperState` into
 * `diagnostic_msgs` and publishes them on the topic the Clearpath
 * `diagnostic_aggregator` consumes. Neither the UR driver nor the Clearpath
 * generator puts the manipulator into that pipeline on its own.
 *
 * Everything here is a pure read over the tree that RosConnectionManager already
 * builds -- no extra topic subscription, so the panel inherits pause, history
 * and reconnect behaviour for free.
 */

// Status names are `<node name>: <task>`; the aggregator keeps that name as the
// leaf of the aggregated path. Matching on the raw name (instead of on the
// analyzer path) makes the panel independent of how the analyzers are grouped.
export const MANIPULATOR_STATUS_PREFIX = "manipulator_diagnostics";

export const ARM_MODE = "Arm Mode";
export const ARM_CONTROL = "Arm Control";
export const ARM_JOINTS = "Arm Joints";
export const ARM_CONTROLLERS = "Arm Controllers";
export const GRIPPER = "Gripper";

export interface ManipulatorStatuses {
    armMode: DiagnosticsEntry | null;
    armControl: DiagnosticsEntry | null;
    armJoints: DiagnosticsEntry | null;
    armControllers: DiagnosticsEntry | null;
    gripper: DiagnosticsEntry | null;
    // Worst severity across all manipulator statuses; -1 when none carry a level.
    level: number;
}

export interface JointRow {
    name: string;
    deg: string;
    rad: string;
    velocity: string;
    effort: string | null;
}

export interface ControllerRow {
    name: string;
    state: string;
}

// Depth-first search for the leaf carrying a given manipulator status.
const findStatus = (entries: DiagnosticsEntry[], task: string): DiagnosticsEntry | null => {
    const suffix = `${MANIPULATOR_STATUS_PREFIX}: ${task}`;
    for (const entry of entries) {
        if (entry.rawName.endsWith(suffix)) {
            return entry;
        }
        const found = findStatus(entry.children, task);
        if (found) {
            return found;
        }
    }
    return null;
};

/*
 * Collect the manipulator statuses out of the aggregated tree.
 *
 * Returns null when none of them are present -- that is the normal case on a
 * robot without an arm, and the panel then renders nothing at all. A *dead*
 * publisher does not end up here: the aggregator lists the statuses as
 * `expected`, so they stay in the tree as STALE entries.
 */
export const collectManipulator = (diagnostics: DiagnosticsEntry[]): ManipulatorStatuses | null => {
    const statuses: ManipulatorStatuses = {
        armMode: findStatus(diagnostics, ARM_MODE),
        armControl: findStatus(diagnostics, ARM_CONTROL),
        armJoints: findStatus(diagnostics, ARM_JOINTS),
        armControllers: findStatus(diagnostics, ARM_CONTROLLERS),
        gripper: findStatus(diagnostics, GRIPPER),
        level: -1,
    };

    const found = [
        statuses.armMode, statuses.armControl, statuses.armJoints,
        statuses.armControllers, statuses.gripper,
    ].filter((entry): entry is DiagnosticsEntry => entry !== null);

    if (found.length === 0) {
        return null;
    }

    statuses.level = found.reduce((worst, entry) => Math.max(worst, entry.severity_level), -1);
    return statuses;
};

// Worst severity of a subset of statuses, for the per-card header badge.
export const worstLevel = (entries: (DiagnosticsEntry | null)[]): number =>
    entries.reduce(
        (worst: number, entry) => (entry ? Math.max(worst, entry.severity_level) : worst),
        -1
    );

export const valueOf = (entry: DiagnosticsEntry | null, key: string): string | null => {
    const value = entry?.values?.[key];
    return value === undefined || value === null ? null : String(value);
};

export const numberOf = (entry: DiagnosticsEntry | null, key: string): number | null => {
    const value = valueOf(entry, key);
    if (value === null) {
        return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
};

// The publisher emits booleans as the strings "true"/"false".
export const boolOf = (entry: DiagnosticsEntry | null, key: string): boolean | null => {
    const value = valueOf(entry, key);
    if (value === "true") return true;
    if (value === "false") return false;
    return null;
};

/*
 * Joint table rows.
 *
 * `joints` is the ordered, comma-separated list of joint names (arm prefix
 * already stripped by the publisher); the per-joint values live under
 * `<joint>_deg`, `<joint>_rad`, `<joint>_vel_rad_s` and optionally
 * `<joint>_effort`. Keeping the order from `joints` matters -- it is the
 * kinematic chain order, not alphabetical.
 */
export const jointRows = (entry: DiagnosticsEntry | null): JointRow[] => {
    const names = valueOf(entry, "joints");
    if (!names) {
        return [];
    }
    return names
            .split(",")
            .map(name => name.trim())
            .filter(name => name.length > 0)
            .map(name => ({
                name,
                deg: valueOf(entry, `${name}_deg`) ?? "-",
                rad: valueOf(entry, `${name}_rad`) ?? "-",
                velocity: valueOf(entry, `${name}_vel_rad_s`) ?? "-",
                effort: valueOf(entry, `${name}_effort`),
            }));
};

// Keys of the Arm Controllers status that are metadata rather than a controller.
const CONTROLLER_META_KEYS = ["required", "active_optional"];

export const controllerRows = (entry: DiagnosticsEntry | null): ControllerRow[] => {
    if (!entry?.values) {
        return [];
    }
    return Object.entries(entry.values)
            .filter(([key]) => !CONTROLLER_META_KEYS.includes(key))
            .map(([name, state]) => ({ name, state: String(state) }))
    // Active controllers first, then alphabetically -- the parked, mutually
    // exclusive command controllers are the uninteresting majority.
            .sort((a, b) => {
                if (a.state !== b.state) {
                    return a.state === "active" ? -1 : b.state === "active" ? 1 : a.state.localeCompare(b.state);
                }
                return a.name.localeCompare(b.name);
            });
};

// Gripper opening as a percentage of the full stroke, clamped to [0, 100].
export const gripperPercent = (entry: DiagnosticsEntry | null): number | null => {
    const percent = numberOf(entry, "width_percent");
    if (percent !== null) {
        return Math.min(100, Math.max(0, percent));
    }
    const width = numberOf(entry, "width_mm");
    const stroke = numberOf(entry, "stroke_mm");
    if (width === null || stroke === null || stroke <= 0) {
        return null;
    }
    return Math.min(100, Math.max(0, (100 * width) / stroke));
};
