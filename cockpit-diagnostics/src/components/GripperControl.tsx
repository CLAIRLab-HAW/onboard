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
 * Everything else here reads. This calls `rg6_control/open` or `/close`
 * (std_srvs/srv/Trigger) on the robot, which closes a 160 mm gripper on a UR5.
 * The guards below are not decoration:
 *
 *  - Admin only, like the diagnostics capture. Cockpit's own permission, so it
 *    follows whatever the host already decided about this user.
 *  - Blocked while the arm reports `external_control: running`. On this robot
 *    every gripper command tears ExternalControl down, so pressing this during
 *    a trajectory aborts the arm's program. Refusing is cheaper than explaining
 *    afterwards why the motion stopped.
 *  - Blocked with no measurement and while the gripper reports itself busy.
 *  - Blocked while the subsystem is out of service.
 *
 * There is deliberately no optimistic state: the label keeps saying what it
 * said until the robot's own state topic reports the new opening. The RG6 is
 * documented in this project as capable of returning success without moving,
 * so a UI that congratulates itself on the response would be lying at exactly
 * the moment it matters.
 */

const TRIGGER = "std_srvs/srv/Trigger";

interface TriggerResponse {
    success?: boolean;
    message?: string;
}

export interface GripperGuardState {
    connected: boolean;
    isInactive: boolean;
    percent: number | null;
    busy: boolean | null;
    externalControlRunning: boolean;
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
    if (state.externalControlRunning)
        return _("The arm is under external control.");
    return null;
};

export const GripperControl = ({
    ros,
    namespace,
    percent,
    busy,
    isInactive,
    externalControlRunning,
}: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ros: any,
    namespace: string,
    percent: number | null,
    busy: boolean | null,
    isInactive: boolean,
    externalControlRunning: boolean,
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
    const action = shouldClose ? "close" : "open";
    const label = shouldClose ? _("Close gripper") : _("Open gripper");

    const blockedReason = gripperBlockedReason({
        connected: Boolean(ros),
        isInactive,
        percent,
        busy,
        externalControlRunning,
    });

    const run = async () => {
        setPending(true);
        setFailure(null);
        try {
            const service = new ROSLIB.Service({
                ros,
                name: `${namespace}/manipulators/rg6_control/${action}`,
                serviceType: TRIGGER,
            });
            const response = await service.call({}) as TriggerResponse;
            // The service answered. `success: false` is a refusal, not a crash,
            // and carries the driver's own explanation -- show it verbatim.
            if (response && response.success === false) {
                setFailure(response.message || _("The gripper refused the command."));
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
