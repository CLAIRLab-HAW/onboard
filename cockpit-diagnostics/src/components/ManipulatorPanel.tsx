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

import React from 'react';
import {
    Alert,
    Button,
    Card,
    CardBody,
    CardTitle,
    DescriptionList,
    DescriptionListDescription,
    DescriptionListGroup,
    DescriptionListTerm,
    Flex,
    FlexItem,
    Grid,
    GridItem,
    Label,
} from "@patternfly/react-core";
import { Table, Thead, Tr, Th, Tbody, Td } from "@patternfly/react-table";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import {
    boolOf,
    collectManipulator,
    controllerRows,
    gripperPercent,
    jointRows,
    numberOf,
    valueOf,
    worstLevel,
} from "../utils/manipulatorUtils";
import {
    LEVEL_INACTIVE,
    LEVEL_OK,
    LEVEL_STALE,
    LEVEL_WARN,
} from "../utils/severity";
import { variantForLevel } from "../utils/summary";
import { GripperControl } from "./GripperControl";
import { GripperGraphic } from "./GripperGraphic";
import { severityLabel } from "./SeverityIcon";

const _ = cockpit.gettext;

/*
 * Dedicated view for the arm and the end effector.
 *
 * The generic tree below already contains these statuses, but reading a joint
 * pose or a gripper opening out of a collapsed tree of key/value pairs is
 * tedious in exactly the moments where it matters (arm in a protective stop,
 * gripper stuck closed). This panel renders the same data in the shape an
 * operator actually looks for, and stays silent on robots without a
 * manipulator: no manipulator statuses in the tree -> nothing is rendered.
 */

const boolText = (value: boolean | null, yes: string, no: string): string => {
    if (value === null) return _("unknown");
    return value ? yes : no;
};

const Term = ({ label, children }: { label: string, children: React.ReactNode }) => (
    <DescriptionListGroup>
        <DescriptionListTerm>{label}</DescriptionListTerm>
        <DescriptionListDescription>{children}</DescriptionListDescription>
    </DescriptionListGroup>
);

/*
 * One line per status that is not plain OK, carrying the publisher's own
 * message (which already says what to do -- "arm switched off", "tool voltage
 * off", ...). Clicking it selects the status in the tree table below, which
 * opens the detail drawer with the full key/value list.
 *
 * Out-of-service statuses get a muted line instead of an alert: they are the
 * *explanation* for the grey card, not something to act on.
 */
const StatusAlerts = ({
    entries,
    setSelectedRawName,
}: {
    entries: (DiagnosticsEntry | null)[],
    setSelectedRawName: (rawName: string | null) => void,
}) => (
    <>
        {entries
                .filter((entry): entry is DiagnosticsEntry =>
                    entry !== null &&
                    (entry.severity_level > LEVEL_OK || entry.severity_level === LEVEL_INACTIVE))
                .map(entry => (entry.severity_level === LEVEL_INACTIVE
                    ? (
                        <div key={entry.rawName} className="manipulator-note">
                            {entry.message || _("No message")}{" "}
                            <Button variant="link" isInline onClick={() => setSelectedRawName(entry.rawName)}>
                                {_("Show details")}
                            </Button>
                        </div>
                    )
                    : (
                        <Alert
                            key={entry.rawName}
                            isInline
                            isPlain
                            variant={entry.severity_level === LEVEL_WARN
                                ? "warning"
                                : entry.severity_level === LEVEL_STALE ? "info" : "danger"}
                            title={entry.message || _("No message")}
                            className="manipulator-alert"
                        >
                            <Button variant="link" isInline onClick={() => setSelectedRawName(entry.rawName)}>
                                {_("Show details")}
                            </Button>
                        </Alert>
                    )))}
    </>
);

const ArmCard = ({
    armMode,
    armControl,
    armJoints,
    armControllers,
    setSelectedRawName,
}: {
    armMode: DiagnosticsEntry | null,
    armControl: DiagnosticsEntry | null,
    armJoints: DiagnosticsEntry | null,
    armControllers: DiagnosticsEntry | null,
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const robotMode = valueOf(armMode, "robot_mode");
    const safetyMode = valueOf(armMode, "safety_mode");
    const externalControl = valueOf(armControl, "external_control");
    const motionLive = valueOf(armControl, "motion_interface") === "live";
    const rate = valueOf(armControl, "joint_state_rate_hz");
    const joints = jointRows(armJoints);
    const controllers = controllerRows(armControllers);
    const activeControllers = controllers.filter(c => c.state === "active").length;
    const level = worstLevel([armMode, armControl, armJoints, armControllers]);
    // Out of service: the readings are last-known values, not live state. Dim
    // them so nobody reads a joint angle off a powered-down arm as current.
    const isInactive = level === LEVEL_INACTIVE;

    return (
        <div className={`state-card state-card-${variantForLevel(level)}`}>
            <h3 className="state-card-title">
                {_("Arm")}
                {/*
                  * No visible state marker here: the card's left stripe is the
                  * one carrier, per the rule that a surface encodes its state
                  * exactly once. The word stays for screen readers, which the
                  * stripe cannot reach.
                  */}
                <span className="pf-v6-screen-reader">{severityLabel(level)}</span>
            </h3>
            <div className="manipulator-subtitle">{valueOf(armMode, "robot_ip")
                ? cockpit.format(_("UR5 at $0"), valueOf(armMode, "robot_ip"))
                : _("UR5")}
            </div>
            <div {...(isInactive ? { className: "manipulator-out-of-service" } : {})}>
                <StatusAlerts
                    entries={[armMode, armControl, armJoints, armControllers]}
                    setSelectedRawName={setSelectedRawName}
                />
                <DescriptionList isHorizontal isCompact>
                    <Term label={_("Robot mode")}>{robotMode ?? _("unknown")}</Term>
                    <Term label={_("Safety mode")}>{safetyMode ?? _("unknown")}</Term>
                    <Term label={_("External control")}>{externalControl ?? _("unknown")}</Term>
                    {/*
                      * The joint_state stream is the honest liveness signal: it only
                      * flows while the ros2_control hardware interface is active.
                      * External control can read "running" over a dead motion link.
                      */}
                    <Term label={_("Motion link")}>
                        {motionLive ? _("live") : _("dead")}
                        {rate && motionLive ? <span className="manipulator-hint">{cockpit.format(_("$0 Hz"), rate)}</span> : null}
                    </Term>
                    <Term label={_("Controllers")}>
                        {controllers.length > 0
                            ? cockpit.format(_("$0 of $1 active"), activeControllers, controllers.length)
                            : _("unknown")}
                    </Term>
                </DescriptionList>

                {joints.length > 0 && (
                    <Table
                        aria-label={_("Arm Joints Table")}
                        borders={false}
                        variant="compact"
                        className="manipulator-joints"
                    >
                        <Thead>
                            <Tr>
                                <Th>{_("Joint")}</Th>
                                <Th modifier="fitContent">{_("Position")}</Th>
                                <Th modifier="fitContent">{_("Velocity")}</Th>
                                {joints.some(joint => joint.effort !== null) && <Th modifier="fitContent">{_("Effort")}</Th>}
                            </Tr>
                        </Thead>
                        <Tbody>
                            {joints.map(joint => (
                                <Tr key={joint.name}>
                                    <Td dataLabel={_("Joint")}>{joint.name}</Td>
                                    <Td dataLabel={_("Position")} modifier="nowrap">
                                        {joint.deg}&nbsp;° <span className="manipulator-hint">({joint.rad}&nbsp;rad)</span>
                                    </Td>
                                    <Td dataLabel={_("Velocity")} modifier="nowrap">{joint.velocity}&nbsp;rad/s</Td>
                                    {joints.some(j => j.effort !== null) && (
                                        <Td dataLabel={_("Effort")} modifier="nowrap">{joint.effort ?? "-"}</Td>
                                    )}
                                </Tr>
                            ))}
                        </Tbody>
                    </Table>
                )}

                {controllers.length > 0 && (
                    <Flex className="manipulator-controllers" spaceItems={{ default: 'spaceItemsXs' }} flexWrap={{ default: 'wrap' }}>
                        {controllers.map(controller => (
                            <FlexItem key={controller.name}>
                                <Label isCompact color={controller.state === "active" ? "green" : "grey"}>
                                    {controller.name}
                                </Label>
                            </FlexItem>
                        ))}
                    </Flex>
                )}
            </div>
        </div>
    );
};

const GripperCard = ({
    gripper,
    setSelectedRawName,
    ros,
    namespace,
}: {
    gripper: DiagnosticsEntry | null,
    setSelectedRawName: (rawName: string | null) => void,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ros?: any,
    // Union rather than optional: `exactOptionalPropertyTypes` forbids handing
    // an optional prop an explicit undefined, and the panel's own namespace is
    // undefined until the robot config has been read.
    namespace: string | undefined,
}) => {
    const percent = gripperPercent(gripper);
    const widthMm = valueOf(gripper, "width_mm");
    const strokeMm = valueOf(gripper, "stroke_mm");
    const gripDetected = boolOf(gripper, "grip_detected");
    const busy = boolOf(gripper, "busy");
    /*
     * Tool voltage is MEASURED at the arm's tool connector. Until the
     * rg6_control retirement this line showed the driver's own setpoint
     * (`tool_power_commanded`), which stayed true after the arm was powered
     * down -- over the Tool-DO path an honest number was never available.
     * The URCap path leaves the supply to the arm, so what is left to report
     * is what the connector actually carries, paired with `signal_valid`:
     * "24 V, no signal" is a tool that has power and still does not answer.
     */
    const toolVoltage = numberOf(gripper, "tool_output_voltage_v");
    const signalValid = boolOf(gripper, "signal_valid");
    /*
     * Only the URCap endpoint reports this (`rg_get_safety_failed`); it had no
     * equivalent on the Tool-DO path, where the old "Force preset" line sat.
     */
    const safetyFailed = boolOf(gripper, "safety_failed");
    const forceRaw = numberOf(gripper, "force_raw_v");
    const level = worstLevel([gripper]);
    const isInactive = level === LEVEL_INACTIVE;

    return (
        <div className={`state-card state-card-${variantForLevel(level)}`}>
            <h3 className="state-card-title">
                {_("End effector")}
                {/*
                  * No visible state marker here: the card's left stripe is the
                  * one carrier, per the rule that a surface encodes its state
                  * exactly once. The word stays for screen readers, which the
                  * stripe cannot reach.
                  */}
                <span className="pf-v6-screen-reader">{severityLabel(level)}</span>
            </h3>
            <div className="manipulator-subtitle">{_("OnRobot RG6")}</div>
            <div {...(isInactive ? { className: "manipulator-out-of-service" } : {})}>
                <StatusAlerts entries={[gripper]} setSelectedRawName={setSelectedRawName} />
                {/*
                  * Readings and picture side by side: stacked, the drawing pushed
                  * six short rows of text a screenful down for no gain. They wrap
                  * back to one column when the card gets narrow.
                  */}
                <div className="rg6-layout">
                    <div className="rg6-readings">
                        <DescriptionList isHorizontal isCompact>
                            <Term label={_("Grip detected")}>
                                {boolText(gripDetected, _("object held"), _("no object"))}
                            </Term>
                            <Term label={_("Motion")}>
                                {boolText(busy, _("moving"), _("settled"))}
                            </Term>
                            {/*
                      * Without tool voltage the RG6 answers nothing at all. After an
                      * arm restart that is briefly normal -- the supply comes up with
                      * the arm, and nothing in ROS can raise it since the RTDE recipe
                      * split took Tool-DO away.
                      */}
                            <Term label={_("Tool power")}>
                                {toolVoltage === null ? _("unknown") : `${toolVoltage.toFixed(0)} V`}
                                {signalValid === false && toolVoltage !== null && toolVoltage > 0 && (
                                    <span className="manipulator-hint">{_("powered, no signal")}</span>
                                )}
                            </Term>
                            <Term label={_("Safety")}>
                                {boolText(safetyFailed, _("fault latched"), _("ok"))}
                            </Term>
                            <Term label={_("Last command")}>
                                {valueOf(gripper, "last_command") ?? _("unknown")}
                            </Term>
                            <Term label={_("Force signal")}>
                                {forceRaw === null ? _("unknown") : `${forceRaw.toFixed(2)} V`}
                            </Term>
                        </DescriptionList>
                    </div>
                    <div className="rg6-visual">
                        <GripperGraphic
                            percent={percent}
                            widthMm={widthMm}
                            strokeMm={strokeMm}
                            gripDetected={gripDetected}
                        />
                        {namespace && (
                            <GripperControl
                                ros={ros}
                                namespace={namespace}
                                percent={percent}
                                busy={busy}
                                isInactive={isInactive}
                            />
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export const ManipulatorPanel = ({
    diagnostics,
    setSelectedRawName,
    ros,
    namespace,
}: {
    diagnostics: DiagnosticsEntry[],
    setSelectedRawName: (rawName: string | null) => void,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ros?: any,
    namespace?: string,
}) => {
    const manipulator = collectManipulator(diagnostics);

    // No manipulator diagnostics at all -> this robot has no arm (or the
    // publisher was never installed). Render nothing rather than an empty card.
    if (!manipulator) {
        return null;
    }

    return (
        <Card>
            <CardTitle component="h2" className="diagnostics-title">
                <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem>{_("Manipulator")}</FlexItem>
                    <FlexItem>
                        <span className="pf-v6-screen-reader">
                            {severityLabel(manipulator.level)}
                        </span>
                    </FlexItem>
                </Flex>
            </CardTitle>
            <CardBody>
                {/*
                  * `md`/etc. are viewport breakpoints, not container ones -- and since
                  * Task 11 this panel sits in a column that is roughly half the page
                  * (.workspace only stacks at <= 1200px). Between ~1200 and ~1500px
                  * viewport width that put the two tiles side by side in ~350px and
                  * ~250px, too narrow for the arm tile's four-column joint table
                  * (nowrap cells that cannot shrink) and overflowing the page. `span`
                  * (no breakpoint) always stacks them, which is the right call in a
                  * column this narrow regardless of viewport width.
                  */}
                <Grid hasGutter>
                    <GridItem span={12}>
                        <ArmCard
                            armMode={manipulator.armMode}
                            armControl={manipulator.armControl}
                            armJoints={manipulator.armJoints}
                            armControllers={manipulator.armControllers}
                            setSelectedRawName={setSelectedRawName}
                        />
                    </GridItem>
                    <GridItem span={12}>
                        <GripperCard
                            gripper={manipulator.gripper}
                            setSelectedRawName={setSelectedRawName}
                            ros={ros}
                            namespace={namespace}
                        />
                    </GridItem>
                </Grid>
            </CardBody>
        </Card>
    );
};
