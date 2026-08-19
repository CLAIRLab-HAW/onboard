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

import React from 'react';
import { Alert, Button } from "@patternfly/react-core";

import cockpit from 'cockpit';

import * as ROSLIB from "../roslib";

const _ = cockpit.gettext;

/*
 * `cockpit.permission` is absent from the bundled cockpit type stub -- the
 * diagnostics capture hits the same gap and simply carries the type error.
 * Typed locally here instead, so this feature does not add a second permanent
 * entry to the project's tsc baseline.
 */
interface CockpitPermission {
    allowed: boolean;
    addEventListener(type: string, handler: () => void): void;
    removeEventListener(type: string, handler: () => void): void;
    close(): void;
}

const adminPermission = (): CockpitPermission =>
    (cockpit as unknown as { permission: (options: { admin: boolean }) => CockpitPermission })
            .permission({ admin: true });

/*
 * The one control on this page that moves hardware.
 *
 * Everything else here reads. This sends a `control_msgs/GripperCommand` goal
 * to the RG6 bridge, which closes a 160 mm gripper on a UR5.
 *
 * Why a service call rather than an action client: a ROS 2 action IS a set of
 * services underneath, and the bridge on this robot advertises the hidden ones
 * (`include_hidden: true`, `service_whitelist: ['.*']` -- read off the running
 * node, 2026-08-19). Calling `.../gripper_cmd/_action/send_goal` therefore asks
 * nothing of this transport it cannot already do, and the transport carries
 * topics and services only -- a real action client was never on the table.
 * Until the rg6_control retirement this called `rg6_control/open` / `/close`
 * (std_srvs/Trigger); those services went with the driver.
 *
 * The guards below are not decoration:
 *
 *  - Admin only, like the diagnostics capture. Cockpit's own permission, so it
 *    follows whatever the host already decided about this user.
 *  - Blocked with no measurement and while the gripper reports itself busy.
 *    The bridge accepts one command at a time and refuses a second one
 *    mid-travel instead of queueing it, so a disabled button is the honest one.
 *  - Blocked while the subsystem is out of service.
 *
 * There is deliberately NO ExternalControl guard any more. It existed because
 * every command over the old Tool-DO path tore ExternalControl down. The bridge
 * speaks XML-RPC to the URCap and leaves the arm's program alone: measured on
 * the a200-0553 on 2026-08-19 with two goals (154 -> 124 -> 154 mm) while
 * `robot_program_running` stayed true throughout and the arm moved 0.0001 rad,
 * an order of magnitude below encoder drift.
 *
 * There is deliberately no optimistic state: the label keeps saying what it
 * said until the robot's own state topic reports the new opening. The RG6 is
 * documented in this project as capable of answering before it has moved,
 * so a UI that congratulates itself on the response would be lying at exactly
 * the moment it matters.
 */

const SEND_GOAL = "control_msgs/action/GripperCommand_SendGoal";

/*
 * GripperCommand carries the finger JOINT, not the opening -- the bridge and
 * the URDF convert it with the same gear table. 0 rad is open, 1.25478 rad is
 * fully closed (read out of rg6_finger_kinematics.json, not copied from prose).
 */
const OPEN_RAD = 0.0;
const CLOSED_RAD = 1.25478;

/*
 * `max_effort <= 0` is GripperCommand's own "take what fits", and the bridge
 * then applies its configured profile force (40 N on this robot). Naming a
 * number here would mean inventing a grip force from a web page, for a gripper
 * the operator may not be standing next to.
 */
const PROFILE_EFFORT = 0.0;

interface SendGoalResponse {
    accepted?: boolean;
}

/*
 * An action identifies its goal by UUID, and calling send_goal directly means
 * nobody generates one for us. Uniqueness per goal is all that is required.
 */
const newGoalId = () => crypto.getRandomValues(new Uint8Array(16));

/*
 * The request the button sends, pulled out so its SHAPE can be tested.
 *
 * `command` sits at the top level, NOT wrapped in a `goal`. The rmw definition
 * of a SendGoal request nests the action's goal, but what the bridge advertises
 * -- and therefore what the message writer serialises against -- is flattened:
 *
 *     unique_identifier_msgs/UUID goal_id
 *     GripperCommand command
 *
 * (read off the running foxglove_bridge on 2026-08-19). A wrongly nested
 * request does not fail: unknown fields are dropped, missing ones are written
 * as zero, so `position` arrives as 0.0 rad and the bridge dutifully opens the
 * gripper. That was measured -- two goals accepted, both logged on the robot as
 * "GripperCommand 153 mm", neither of them the commanded 0 mm.
 */
export const gripperGoalRequest = (shouldClose: boolean) => ({
    goal_id: { uuid: newGoalId() },
    command: {
        position: shouldClose ? CLOSED_RAD : OPEN_RAD,
        max_effort: PROFILE_EFFORT,
    },
});

export interface GripperGuardState {
    connected: boolean;
    isInactive: boolean;
    percent: number | null;
    busy: boolean | null;
}

/*
 * Why the command is refused, or null when it may go ahead.
 *
 * Pulled out of the component on purpose: this is the safety-relevant decision
 * of the whole feature, and the component cannot be exercised by the test
 * harness (`renderToStaticMarkup` never runs the effect that reads the admin
 * permission, so the rendered output is always the fail-closed empty one).
 * A guard nobody can test is a guard nobody should trust.
 *
 * Order matters: the most fundamental obstacle is reported first, so the
 * operator is told "not connected" rather than "still moving" when both are
 * true and only one of them is actionable.
 */
export const gripperBlockedReason = (state: GripperGuardState): string | null => {
    if (!state.connected) return _("Not connected to the robot.");
    if (state.isInactive) return _("The end effector is out of service.");
    if (state.percent === null) return _("No opening is being reported.");
    if (state.busy === true) return _("The gripper is still moving.");
    return null;
};

export const GripperControl = ({
    ros,
    namespace,
    percent,
    busy,
    isInactive,
}: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ros: any,
    namespace: string,
    percent: number | null,
    busy: boolean | null,
    isInactive: boolean,
}) => {
    const [admin, setAdmin] = React.useState(false);
    const [pending, setPending] = React.useState(false);
    const [failure, setFailure] = React.useState<string | null>(null);

    React.useEffect(() => {
        const permission = adminPermission();
        const update = () => setAdmin(permission.allowed);
        permission.addEventListener("changed", update);
        update();
        return () => {
            permission.removeEventListener("changed", update);
            permission.close();
        };
    }, []);

    if (!admin) {
        return null;
    }

    // Which way to move is read off the same measurement the drawing uses.
    const shouldClose = percent !== null && percent > 50;
    const label = shouldClose ? _("Close gripper") : _("Open gripper");

    const blockedReason = gripperBlockedReason({
        connected: Boolean(ros),
        isInactive,
        percent,
        busy,
    });

    const run = async () => {
        setPending(true);
        setFailure(null);
        try {
            const service = new ROSLIB.Service({
                ros,
                name: `${namespace}/manipulators/rg6_gripper_controller/gripper_cmd/_action/send_goal`,
                serviceType: SEND_GOAL,
            });
            const response = await service.call(
                gripperGoalRequest(shouldClose)) as SendGoalResponse;
            /*
             * The bridge answered. `accepted: false` is a refusal, not a crash
             * -- it is what a second command during travel gets. A send_goal
             * response carries no message field, so the wording has to be ours;
             * what the gripper is actually doing stays on the state topic.
             */
            if (response && response.accepted === false) {
                setFailure(_("The gripper refused the command."));
            }
        } catch (error) {
            setFailure(error instanceof Error ? error.message : String(error));
        } finally {
            setPending(false);
        }
    };

    return (
        <div className="rg6-control">
            <Button
                variant="secondary"
                isDisabled={blockedReason !== null || pending}
                isLoading={pending}
                onClick={() => { run() }}
            >
                {label}
            </Button>
            {blockedReason && <div className="rg6-control-reason">{blockedReason}</div>}
            {failure && (
                <Alert
                    variant="danger"
                    isInline
                    isPlain
                    title={failure}
                    className="rg6-control-failure"
                />
            )}
        </div>
    );
};
